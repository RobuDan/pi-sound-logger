import asyncio
import logging
import os
import wave
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import sounddevice as sd
import soundfile as sf
from pydub import AudioSegment
from .help_functions.get_device_index import get_device_index

class AudioStream:
    """
    Captures audio, alligned with timestamp, in order to be write as WAV files.

    Responsibilities:
    - Initialize and open the correct input device.
    - Continuously record short audio chunks (default 1s).
    - Pass each chunk to WavWriter for file-based storage.
    """
    def __init__(self, sample_rate, timestamp_provider, chunk_duration=1.0):        
        """
        Initialize the audio stream with sampling parameters.
        """
        self.sample_rate = sample_rate
        self.chunk_duration = chunk_duration
        self.timestamp_provider = timestamp_provider
        self.channels = 1
        self.dtype = 'int16'

        self.device_index = get_device_index()
        self.wav_writer = WavWriter(timestamp_provider, sample_rate=self.sample_rate, channels=self.channels)

        self.run_flag = False
        self.audio_task = None

        if not self.timestamp_provider:
            raise ValueError("TimestampProvider is required for AudioStream.")

    async def start(self):
        """
        Starts the background recording task as an asyncio coroutine.
        """
        logging.info("AudioStream starting...")
        self.run_flag = True
        self.audio_task = asyncio.create_task(self._run_loop())

    async def _run_loop(self):
        frames_per_chunk = int(self.sample_rate * self.chunk_duration)

        try:
            with sd.InputStream(
                samplerate=self.sample_rate,
                channels=self.channels,
                dtype=self.dtype,
                device=self.device_index,
            ) as stream:

                while self.run_flag:
                    try:
                        # 1) Grab the “official” timestamp from the provider
                        timestamp = self.timestamp_provider.get_timestamp()
                        aligned_minute = timestamp.replace(second=0, microsecond=0)

                        # 2) Watchdog: if more than 60s passed since current_file_start_time, force rotate
                        cfst = self.wav_writer.current_file_start_time
                        if cfst:
                            now = self.timestamp_provider.get_timestamp()
                            elapsed = (now - cfst).total_seconds()
                            if now >= cfst + timedelta(seconds=63):
                                logging.warning(
                                    "[AudioStream] >60s elapsed since last rotation; forcing rotate"
                                )
                                self.wav_writer.force_rotate()

                        # 3) Read one chunk of audio (offloaded to a thread to avoid blocking)
                        audio_frames, _ = await asyncio.to_thread(
                            stream.read, frames_per_chunk
                        )
                        audio_bytes = np.array(audio_frames).flatten().astype(np.int16)

                        # 4) Normal “minute‐aligned” rotation & write
                        self.wav_writer.update_timestamp(aligned_minute)
                        self.wav_writer.write(audio_bytes)

                    except (SystemExit, asyncio.CancelledError):
                        logging.info("[AudioStream] Shutdown signal received inside read loop.")
                        break

                    except Exception as e:
                        logging.error(f"[AudioStream] Read error: {e}")
                        await asyncio.sleep(1)

        except asyncio.CancelledError:
            logging.info("AudioStream task cancelled.")
        except Exception as e:
            logging.error(f"[AudioStream Error] {e}")

    async def cleanup(self):
        """
        Cancels the recording task and ensures the current WAV file is finalized.
        """
        logging.info("Cleaning up AudioStream...")
        if self.audio_task:
            self.audio_task.cancel()
            try:
                await self.audio_task
            except asyncio.CancelledError:
                logging.info("Audio stream task cleanly cancelled.")

        try:
            self.wav_writer.close()
        except Exception as e:
            logging.error(f"Error closing WavWriter: {e}")
        logging.info("AudioStream cleanup complete.")


class WavWriter:
    """
    Handles writing PCM audio data to timestamp-aligned WAV files and converting them to MP3.

    Responsibilities:
    - Create and rotate WAV files every new aligned minute.
    - Write incoming audio frames to the current file.
    - Convert closed WAV files to MP3 and move them to the final folder.
    """
    def __init__(self, timestamp_provider, sample_rate=48000, channels=1, sampwidth=2):
        """
        Initialize WavWriter and create required folders.
        """
        self.sample_rate = sample_rate
        self.channels = channels
        self.sampwidth = sampwidth
        self.wavfile = None
        self.current_file_path = None
        self.construct_dir, self.final_dir = self._setup_directories()
        self.current_file_start_time = None
        self.timestamp_provider = timestamp_provider

    def _setup_directories(self):
        """
        Makes sure directories are created. Files are going to be rotated.
        """
        base_path = os.path.join('..', 'data_storage')
        script_dir = os.path.dirname(os.path.abspath(__file__))

        construct_path = os.path.join(script_dir, base_path, 'construct_audio')
        final_path = os.path.join(script_dir, base_path, 'audio')

        os.makedirs(construct_path, exist_ok=True)
        os.makedirs(final_path, exist_ok=True)

        return construct_path, final_path

    def _open_new_file(self, start_time: datetime):
        """
        Opens a new WAV file aligned to the provided start time.
        """
        if self.wavfile:
            self.close()
        formatted_time = start_time.strftime("%Y-%m-%d %H-%M-00.wav")
        self.current_file_path = os.path.join(self.construct_dir, formatted_time)
        self.wavfile = wave.open(self.current_file_path, 'wb')
        self.wavfile.setnchannels(self.channels)
        self.wavfile.setsampwidth(self.sampwidth)
        self.wavfile.setframerate(self.sample_rate)
        self.current_file_start_time = start_time

    def update_timestamp(self, aligned_time: datetime):
        """
        Checks if the current file needs to be rotated based on a new timestamp.
        """
        if not self.current_file_start_time or aligned_time > self.current_file_start_time:
            self._open_new_file(aligned_time)

    def write(self, audio_data):
        """
        Writes a numpy audio buffer to the current WAV file.
        """
        if not self.wavfile:
            self._open_new_file(datetime.now())
        if isinstance(audio_data, np.ndarray):
            pcm_data = audio_data.astype(np.int16).tobytes()
            self.wavfile.writeframes(pcm_data)
        else:
            logging.warning("Unsupported audio data format in write(). Expected np.ndarray.")

    def close(self):
        """
        Finalizes and closes the current WAV file.
        Converts it to MP3 and deletes the temporary WAV.
        """
        if self.wavfile:
            self.wavfile.close()
            self.wavfile = None

            try:
                mp3_name = os.path.splitext(os.path.basename(self.current_file_path))[0] + ".mp3"
                mp3_path = os.path.join(self.final_dir, mp3_name)

                audio = AudioSegment.from_wav(self.current_file_path)
                audio.export(mp3_path, format="mp3", bitrate="256k")
                os.remove(self.current_file_path)

            except Exception as e:
                logging.error(f"[WavWriter] Error during MP3 conversion: {e}")

    def force_rotate(self):
        """
        Immediately closes the current WAV (if open) and starts a new file for the current minute.
        """
        # 1) If a WAV is open, close & convert it now
        if self.wavfile:
            self.wavfile.close()
            self.wavfile = None

            try:
                mp3_name = os.path.splitext(os.path.basename(self.current_file_path))[0] + ".mp3"
                mp3_path = os.path.join(self.final_dir, mp3_name)

                audio = AudioSegment.from_wav(self.current_file_path)
                audio.export(mp3_path, format="mp3", bitrate="256k")
                os.remove(self.current_file_path)
                logging.info(f"[WavWriter] force-rotated and converted: {mp3_name}")

            except Exception as e:
                logging.error(f"[WavWriter] Error during forced MP3 conversion: {e}")

        # 2) Open a brand-new WAV for “now” floored to the minute
        provider_now = self.timestamp_provider.get_timestamp()
        new_minute = provider_now.replace(second=0, microsecond=0)
        formatted_time = new_minute.strftime("%Y-%m-%d %H-%M-00.wav")
        new_path = os.path.join(self.construct_dir, formatted_time)
        self.wavfile = wave.open(new_path, "wb")
        self.wavfile.setnchannels(self.channels)
        self.wavfile.setsampwidth(self.sampwidth)
        self.wavfile.setframerate(self.sample_rate)
        self.current_file_path = new_path
        self.current_file_start_time = new_minute

        logging.info(f"[WavWriter] force_rotate → opened {formatted_time}")