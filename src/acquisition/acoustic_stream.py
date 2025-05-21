import asyncio
import logging
import datetime
import time

from .help_functions.average import calculate_laeq


class AcousticStream:
    """
    Continuously acquires and logs acoustic parameters (e.g., LAeq, LAFmin, LAFmax) 
    from a microphone device in sync with real-time seconds.
    """

    def __init__(self, device, acoustic_parameters, mysql_pool, sample_interval, timestamp_provider=None):
        """
        Initializes the stream with device, target parameters, and timing settings.
        """
        self.device = device
        self.acoustic_parameters = acoustic_parameters
        self.mysql_pool = mysql_pool
        self.sample_interval = sample_interval
        self.samples_per_second = int(1 / self.sample_interval)
        self.timestamp_provider = timestamp_provider
        self.run_flag = False
        self.stream_task = None

        if not self.timestamp_provider:
            raise ValueError("TimestampProvider is required for AcousticStream.")

    def wait_for_next_second(self) -> float:
        """
        Returns the sleep duration needed to align with the next full second.
        """
        return self.timestamp_provider.get_next_second_sleep_time()

    async def start(self):
        """
        Starts the stream task if not already running.
        """
        logging.info("AcousticStream starting...")
        if self.run_flag:
            logging.info("AcousticStream already running.")
            return

        if self.timestamp_provider:
            start_ts = self.timestamp_provider.get_start_timestamp()
            if start_ts:
                logging.info(f"Aligned start timestamp: {start_ts.isoformat(timespec='milliseconds')}")

        self.run_flag = True
        self.stream_task = asyncio.create_task(self._run_loop())

    async def _run_loop(self):
        """
        Main loop: aligns to wall time, samples data, logs results once per second.
        """
        try:
            await asyncio.sleep(self.wait_for_next_second())
            logging.info("Stream aligned to next second.")

            last_cycle_start = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0)

            while self.run_flag:
                base_time = last_cycle_start
                laf_values = []
                leq_values = []

                for i in range(self.samples_per_second):
                    try:
                        laf = self.device.read_level()
                        leq = self.device.read_leq()
                        laf_values.append(laf)
                        leq_values.append(leq)
                    except Exception as e:
                        logging.error(f"[Sample Error] {e}")
                        continue

                    # Sync sampling rate to real-time clock
                    target = base_time.timestamp() + ((i + 1) * self.sample_interval)
                    await asyncio.sleep(max(0, target - time.time()))

                if len(laf_values) < self.samples_per_second:
                    logging.warning(f"[{base_time}] Incomplete sample set. Skipping.")
                    continue

                try:
                    log_parts = []

                    if "LAF" in self.acoustic_parameters:
                        log_parts.append(f"LAF={laf_values[0]:.2f} dB")
                    if "LAFmin" in self.acoustic_parameters:
                        log_parts.append(f"LAFmin={min(laf_values):.2f} dB")
                    if "LAFmax" in self.acoustic_parameters:
                        log_parts.append(f"LAFmax={max(laf_values):.2f} dB")
                    if "LAeq" in self.acoustic_parameters:
                        log_parts.append(f"LAeq={calculate_laeq(leq_values):.2f} dB")

                    log_time = base_time.astimezone(self.timestamp_provider.tz).isoformat(timespec="milliseconds")
                    logging.info(f"[{log_time}] " + " | ".join(log_parts))

                except Exception as e:
                    logging.error(f"[Post-process Error] {e}")

                last_cycle_start = base_time + datetime.timedelta(seconds=1)

        except asyncio.CancelledError:
            logging.info("AcousticStream task cancelled.")
        except Exception as e:
            logging.error(f"Stream loop failure: {e}")

    async def cleanup(self):
        """
        Cancels the stream task if active.
        """
        logging.info("Cleaning up AcousticStream...")
        if self.stream_task:
            self.stream_task.cancel()
            await self.stream_task
        logging.info("Cleanup complete.")
