import os
import asyncio
import logging
from datetime import datetime
from collections import deque

class AudioStallDetector:
    """
    Monitors the audio output folder. If no new audio file timestamp is detected
    over a specified duration, it triggers a recovery callback (e.g., to restart acquisition).
    """

    def __init__(self, callback, scan_interval=5, max_stall_duration_minutes=3):
        """
        Args:
            callback (coroutine): Function to call when a stall is detected.
            scan_interval (int): Seconds between scans.
            max_stall_duration_minutes (int): Time without new files before triggering callback.
        """
        self.callback = callback
        self.scan_interval = scan_interval
        self.max_stall_scans = (60 // scan_interval) * max_stall_duration_minutes

        self.audio_folder_path = self._setup_working_dir()
        self.last_seen_timestamp = None
        self.stall_scan_counter = 0
        self.callback_in_progress = False
        self._stopped = False

    def _setup_working_dir(self):
        """Setup absolute path to the 'audio' directory."""
        dir_of_current_script = os.path.dirname(os.path.abspath(__file__))
        base_path = os.path.abspath(os.path.join(dir_of_current_script, '..'))
        return os.path.join(base_path, 'data_storage', 'audio')

    async def start(self):
        """Begin monitoring loop. Detects audio stalls based on missing timestamp progression."""
        logging.info("[AudioStallDetector] Started monitoring folder: %s", self.audio_folder_path)
        self._stopped = False

        while not self._stopped:
            try:
                latest_ts = self._get_latest_audio_timestamp()

                if latest_ts:
                    if self.last_seen_timestamp is None or latest_ts > self.last_seen_timestamp:
                        self.last_seen_timestamp = latest_ts
                        self.stall_scan_counter = 0
                        logging.info(f"[AudioStallDetector] Detected new timestamp: {latest_ts}")
                    else:
                        self.stall_scan_counter += 1
                        logging.info(f"[AudioStallDetector] No new timestamp. Stall count: {self.stall_scan_counter}")
                else:
                    logging.info("[AudioStallDetector] No files found.")
                    self.stall_scan_counter += 1

                if self.stall_scan_counter >= self.max_stall_scans:
                    if self.callback and not self.callback_in_progress:
                        logging.warning("[AudioStallDetector] No audio updates for %d scans — triggering restart.",
                                        self.stall_scan_counter)
                        self.callback_in_progress = True
                        asyncio.create_task(self._handle_callback())

                await asyncio.sleep(self.scan_interval)

            except Exception as e:
                logging.exception("[AudioStallDetector] Error in monitoring loop: %s", e)
                await asyncio.sleep(self.scan_interval)

    def _get_latest_audio_timestamp(self):
        """
        Extract the newest timestamp from .mp3 filenames in the audio folder.
        Returns:
            datetime or None: latest timestamp, or None if no valid files found.
        """
        try:
            mp3_files = [f for f in os.listdir(self.audio_folder_path) if f.endswith(".mp3")]
            if not mp3_files:
                return None

            timestamps = []
            for fname in mp3_files:
                try:
                    ts = datetime.strptime(fname.replace(".mp3", ""), "%Y-%m-%d %H-%M-%S")
                    timestamps.append(ts)
                except ValueError:
                    logging.warning(f"[AudioStallDetector] Skipping invalid filename: {fname}")
            return max(timestamps) if timestamps else None

        except Exception as e:
            logging.error(f"[AudioStallDetector] Failed to scan folder: {e}")
            return None

    async def _handle_callback(self):
        """Safely run the callback and reset internal flags."""
        try:
            if self.callback:
                await self.callback()
        finally:
            self.callback_in_progress = False
            self.stall_scan_counter = 0  # Reset after restart

    def stop(self):
        """Signal the monitoring loop to exit gracefully."""
        self._stopped = True
