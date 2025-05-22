import sys
import logging
import asyncio
import signal

from utils.log import setup_logging
from utils.env_config_loader import validate_or_exit
from monitoring.monitor_status import MonitorStatus
from acquisition.acquisition_manager import AcquisitionManager
from database.mysql.mysql_connection_manager import MySQLConnectionManager
# TODO: Replace with actual implementation of classes and function

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
        self.mongodb_manager = None
        self.acquisition_manager = None

        self.mysql_ready_event = asyncio.Event()

        self.device_connected_event = asyncio.Event()
        self.device_monitor = MonitorStatus(self.device_connected_event, callback=self.handle_device_disconnected)

        self.tasks = []
        self.acquisition_task = None

    async def start(self):
        """
        Starts required components: database managers and device monitor.
        Waits for MySQL and device connection before launching acquisition.
        """
        logging.info("Starting pi-sound-logger application")

        try:
            # Start MySQL manager and wait for it to establish the pool
            pool = await self.mysql_manager.manager_start()
            # logging.info("MySQL Connection is established.")
            if pool is not None:
                #await self.mongodb_manager.set_mysql_pool(pool)
                self.mysql_ready_event.set()
            else:
                logging.error("Failed to initialize MySQL pool.")
            monitor_task = asyncio.create_task(self.device_monitor.manager_start())
            self.tasks.append(monitor_task)

            await self.device_connected_event.wait()

            serial_path = self.device_monitor.serial_path
            
            if serial_path is None:
                logging.warning("Event was set but serial_path is still None!")
            else:
                logging.info(f"Serial path: {serial_path}")

            self.acquisition_manager = AcquisitionManager(serial_path=serial_path, mysql_manager=self.mysql_manager)
            self.acquisition_task = asyncio.create_task(self.acquisition_manager.manager_start())

            # Wait until the device is connected before proceeding
            #await self.device_connected_event.wait()
            logging.info("NSRT device is ready proceeding to acquisition setup...")

        except Exception as e:
            logging.error(f"Failure due to {e}")


    async def handle_device_disconnected(self):
        """
        Handles device disconnection by stopping acquisition,
        waiting for reconnection, and restarting acquisition.
        """
        if self.acquisition_task:
            self.acquisition_task.cancel()
            try:
                await self.acquisition_task
            except asyncio.CancelledError:
                logging.info("Acquisition task cancelled successfully.")
            try:
                await self.acquisition_manager.manager_stop()
            except Exception as e:
                logging.error(f"Error stopping the manager: {e}")

        await self.device_connected_event.wait()
        serial_path = self.device_monitor.serial_path
        self.acquisition_manager = AcquisitionManager(serial_path=serial_path, mysql_manager=self.mysql_manager)
        self.acquisition_task = asyncio.create_task(self.acquisition_manager.manager_start())
        self.tasks.append(self.acquisition_task)

    async def restart_device_manager(self):
        logging.info("Restarting device manager with the new configuration.")
        await self.acquisition_manager.manager_stop()
        await self.acquisition_manager.manager_start()

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
            await self.acquisition_manager.manager_stop()
        if self.mongodb_manager:
            await self.mongodb_manager.manager_stop()
        if self.mysql_manager:
            await self.mysql_manager.manager_stop()
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