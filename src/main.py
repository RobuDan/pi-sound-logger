import sys
import logging
import asyncio
import signal
import nsrt_mk3_dev

from utils.log import setup_logging
from utils.env_config_loader import validate_or_exit
from monitoring.monitor_status import MonitorStatus
from monitoring.audio_stall_detector import AudioStallDetector
from acquisition.acquisition_manager import AcquisitionManager
from database.mysql.mysql_connection_manager import MySQLConnectionManager
from database.mongodb.mongodb_connection_manager import MongoDBConnectionManager

setup_logging()
validate_or_exit()

class Application:
    """
    Manages the lifecycle of the pi-sound-logger application, including setup, 
    device monitoring, data acquisition, and cleanup.
    """

    def __init__(self):
        """
        Initialize internal components and shared asyncio events.
        """
        self.mysql_manager = MySQLConnectionManager()
        self.mongodb_manager = MongoDBConnectionManager(callback=self.handle_device_disconnected)
        self.acquisition_manager = None

        self.mysql_ready_event = asyncio.Event()

        self.device_connected_event = asyncio.Event()
        self.device_monitor = MonitorStatus(self.device_connected_event, callback=self.handle_device_disconnected)

        self.audio_detector = None

        self.tasks = []
        self.acquisition_task = None

    async def start(self):
        """
        Starts required components: database managers and device monitor.
        Waits for MySQL and device connection before launching acquisition.
        """
        logging.info("Starting pi-sound-logger application")

        try:
            # Start MongoDB manager as an independent, non-blocking task
            mongo_task = asyncio.create_task(self.mongodb_manager.start())
            self.tasks.append(mongo_task)
            logging.info("MongoDB Connection is established.")
            
            # Start MySQL manager and wait for it to establish the pool
            pool = await self.mysql_manager.start()
            logging.info("MySQL Connection is established.")
            if pool is not None:
                await self.mongodb_manager.set_mysql_pool(pool)
                self.mysql_ready_event.set()
            else:
                logging.error("Failed to initialize MySQL pool.")

            # Start monitoring the device presence
            monitor_task = asyncio.create_task(self.device_monitor.start())
            self.tasks.append(monitor_task)

            # Wait until the device is connected before proceeding
            await self.device_connected_event.wait()

            serial_path = self.device_monitor.serial_path
            
            # Preventing empty race contitions
            while serial_path is None:
                logging.warning("Device event se but serial_path is None. Waiting")
                await asyncio.sleep(0.1)
                serial_path = self.device_monitor.serial_path

            # Create the device using serial path and share it across
            device = nsrt_mk3_dev.NsrtMk3Dev(serial_path)

            # Pass to components that are using it
            await self.mongodb_manager.set_device(device)
            self.acquisition_manager = AcquisitionManager(device=device, mysql_manager=self.mysql_manager)

            # Initialization of acquistion component.
            self.acquisition_task = asyncio.create_task(self.acquisition_manager.start())
            self.tasks.append(self.acquisition_task)

            # Initialization of audio monitoring
            self.audio_detector = AudioStallDetector(callback=self.handle_device_disconnected)
            self.audio_detector_task = asyncio.create_task(self.audio_detector.start())
            self.tasks.append(self.audio_detector_task)


            logging.info(f"NSRT device on port {serial_path} is ready. Proceeding to acquisition setup...")

        except Exception as e:
            logging.error(f"Failure due to {e}")


    async def handle_device_disconnected(self):
        """
        Handles device disconnection by stopping acquisition,
        stopping audio monitoring, waiting for reconnection,
        and retrying the acquisition and monitoring startup until successful.
        """
        # Stop AudioStallDetector first if active
        if self.audio_detector:
            self.audio_detector.stop()
            self.audio_detector = None

        if self.audio_detector_task:
            self.audio_detector_task.cancel()
            try:
                await self.audio_detector_task
            except asyncio.CancelledError:
                logging.info("AudioStallDetector task cancelled.")
            self.audio_detector_task = None

        # Stop acquisition
        if self.acquisition_task:
            self.acquisition_task.cancel()
            try:
                await self.acquisition_task
            except asyncio.CancelledError:
                logging.info("Acquisition task cancelled successfully.")
            try:
                await self.acquisition_manager.stop()
            except Exception as e:
                logging.error(f"Error stopping the manager: {e}")

        # Inform MongoDB that the device is disconnected
        self.mongodb_manager.set_device(None)

        # Wait for reconnection signal
        await self.device_connected_event.wait()

        # Wait until serial_path is not None
        serial_path = self.device_monitor.serial_path
        while serial_path is None:
            await asyncio.sleep(0.1)
            serial_path = self.device_monitor.serial_path

        # Attempt to restart acquisition and monitoring
        retry_attempts = 0
        while True:
            retry_attempts += 1
            try:
                logging.info(f"[Application] Attempting acquisition restart (attempt #{retry_attempts})")

                new_device = nsrt_mk3_dev.NsrtMk3Dev(serial_path)
                await self.mongodb_manager.set_device(new_device)
                self.acquisition_manager = AcquisitionManager(device=new_device, mysql_manager=self.mysql_manager)

                self.acquisition_task = asyncio.create_task(self.acquisition_manager.start())
                self.tasks.append(self.acquisition_task)

                # Restart AudioStallDetector
                self.audio_detector = AudioStallDetector(callback=self.handle_device_disconnected)
                self.audio_detector_task = asyncio.create_task(self.audio_detector.start())
                self.tasks.append(self.audio_detector_task)

                logging.info(f"[Application] Acquisition and audio monitoring restarted successfully.")
                break

            except Exception as e:
                logging.error(f"[Application] Acquisition restart failed: {e}")
                await asyncio.sleep(5)  # Wait before retrying


    async def restart_device_manager(self):
        logging.info("Restarting device manager with the new configuration.")
        await self.acquisition_manager.stop()
        await self.acquisition_manager.start()

    async def stop(self):
        """
        Cancels tasks and stops all managers gracefully on shutdown or error.
        """
        logging.info("Stopping application...")

        for task in self.tasks:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                logging.info(f"Task cancelled successfully.")
        if self.acquisition_manager:
            await self.acquisition_manager.stop()
        if self.mongodb_manager:
            await self.mongodb_manager.stop()
        if self.mysql_manager:
            await self.mysql_manager.stop()
        logging.info("Application stopped.")

    async def run(self):
        """
        Runs the full application loop. This keeps the application running
        and catches unexpected exceptions to ensure graceful shutdown.
        """
        try:
            await self.start()
            await asyncio.Future() # Keeps the app running
        except Exception as e:
            logging.error(f" Error encountered: {e}")
        finally:
            await self.stop()

async def main():
    """
    Entrypoint for the asyncio event loop. Initializes the Application 
    instance and handles shutdown on interrupt signals.
    """
    app = Application()

    try: 
        await app.run()
    except (KeyboardInterrupt, SystemExit):
        logging.info("Shutdown signal recevied.")
        await app.stop()
    except Exception as e:
        logging.error(f"Unhandled exception: {e}")
        await app.stop()

def handle_exit(sig, frame):
    raise SystemExit

if __name__ == "__main__":
    signal.signal(signal.SIGTERM, handle_exit)
    signal.signal(signal.SIGINT, handle_exit)
    try:
        asyncio.run(main())
    except SystemExit:
        logging.info("SystemExit raised, existing applicaiton.")
        sys.exit(0)
    except Exception as e:
        logging.error(f"Exception during shutdown: {e}")
        sys.exit(1)