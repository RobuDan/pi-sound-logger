import os
import platform
import asyncio
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

class MonitorStatus:
    """
    Monitors the presence of the NSRT device via serial connection.
    Sets an asyncio.Event when the device is connected, and clears it when disconnected.
    If a callback is provided, it is called when the device disconnects.
    """

    def __init__(self, device_connected_event: asyncio.Event, callback=None):
        self.device_connected_event = device_connected_event
        self.callback = callback
        self.callback_in_progress = False
        self.serial_path = None
        self.scheduler = AsyncIOScheduler()

        # Used for Linux device detection in /dev/serial/by-id/
        self.target_keywords = ["Convergence_Instruments", "NSRT", "mk3"]

    def get_serial_port(self):
        """
        Returns the full path to the target serial device.

        - On Windows: returns hardcoded COM port.
        - On Linux: finds matching symlink in /dev/serial/by-id/.
        """
        if platform.system() == "Windows":
            return "COM6"  # Hardcoded development port
        else:
            base_path = "/dev/serial/by-id/"
            try:
                for entry in os.listdir(base_path):
                    if all(keyword in entry for keyword in self.target_keywords):
                        full_symlink_path = os.path.join(base_path, entry)
                        if os.path.islink(full_symlink_path):
                            resolved_path = os.path.realpath(full_symlink_path)
                            return resolved_path
            except FileNotFoundError:
                logging.warning(f"{base_path} not found. Retrying...")
                return None
            return None

    async def check_serial_device(self):
        """
        Continuously checks for device presence.
        Sets or clears the event based on connection state.
        Triggers callback if disconnection is detected.
        """
        while True:
            # Wait for the device to appear
            while True:
                found_port = self.get_serial_port()
                if found_port:
                    self.serial_path = found_port
                    logging.info(f"Target serial device found at {self.serial_path}")
                    self.device_connected_event.set()
                    break
                else:
                    self.device_connected_event.clear()
                    logging.info("Waiting for target serial device...")
                    await asyncio.sleep(2)

            # Monitor for disconnection
            while self.get_serial_port() == self.serial_path:
                await asyncio.sleep(1)

            # Device disconnected
            logging.warning("Serial device disconnected!")
            self.device_connected_event.clear()

            if self.callback and not self.callback_in_progress:
                self.callback_in_progress = True
                asyncio.create_task(self.handle_callback())

    async def handle_callback(self):
        """
        Calls the provided callback once, then resets the flag.
        """
        try:
            if self.callback:
                await self.callback()
        finally:
            self.callback_in_progress = False

    async def start(self):
        """
        Entry point for the monitoring task.
        Starts scheduled safety resets and runs initial device check.
        """
        try:
            self.schedule_resets()
            await self.check_serial_device()
        except Exception as e:
            logging.info(e)
            
    def schedule_resets(self):
        """
        Schedules the resets at 02:00:03 and 04:00:03 AM using APScheduler.
        """
        if not self.scheduler.running:
            self.scheduler.start()
            logging.info("Scheduler started successfully.")


        self.scheduler.add_job(
            self.execute_scheduled_reset,
            CronTrigger(hour=2, minute=0, second=3),
            id='reset_at_2am',
            replace_existing=True,
        )
        logging.info("Scheduled reset job at 02:00:03 AM.")

        self.scheduler.add_job(
            self.execute_scheduled_reset,
            CronTrigger(hour=13, minute=0, second=3),  
            id='reset_at_1pm',
            replace_existing=True,
        )
        logging.info("Scheduled reset job at 13:00:03 PM.")

    async def execute_scheduled_reset(self):
        """
        Executes the scheduled reset by calling the provided callback function.
        Avoids running if a reset is already in progress.
        """
        if self.callback and not self.callback_in_progress:
            logging.info("Executing scheduled reset.")
            self.callback_in_progress = True
            try:
                await self.handle_callback()
                logging.info("Scheduled reset executed successfully.")
            except Exception as e:
                logging.error(f"Error executing scheduled reset: {e}")
            finally:
                self.callback_in_progress = False
        else:
            logging.warning("Reset skipped because another callback is in progress.")
