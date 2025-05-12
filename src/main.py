import sys
import logging
import asyncio
import signal

from utils.log import setup_logging
from utils.config_loader import validate_or_exit
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
        self.mysql_manager = None
        self.mongodb_manager = None
        self.device_monitor = None
        self.acquisition_manager = None

        self.mysql_ready_event = asyncio.Event()
        self.device_connected_event = asyncio.Event()

        self.tasks = []
        self.acquisition_task = None

    async def start(self):
        """
        Starts required components: database managers and device monitor.
        Waits for MySQL and device connection before launching acquisition.
        """
        logging.info("Starting pi-sound-logger application")

        # TODO: Start MongoDB sync manager (background task)
        # TODO: Start MySql manage and wat for pool
        # TODO: If successful, set mysql_ready_evet

        # TODO: Start DeviceMonitor tasK
        # TODO: SerialDeviceMonitor SHOULD set/clear device_connected_manager as needed

        # TODO: Wait for both mysql_ready_event and device_connected_event
        # TODO: Start SerialAcquisitionManager when both condtions are met

        pass

    async def handle_device_disconnected():
        """
        Handles device disconnection by stopping acquisition,
        waiting for reconnection, and restarting acquisition.
        """
        # TODO: Stop acquisiton manager
        # TODO: Wait for device to be present
        # TODO: Restart acquisiton manger

        pass

    async def stop(self):
        """
        Cancels tasks and stops all managers gracefully on shutdown or error.
        """
        logging.info("Stopping application...")

        # TODO: Cancel tasks and stop managers safely

        pass

    async def run(self):
        """
        Runs the full application loop. This keeps the application running
        and catches unexpected exceptions to ensure graceful shutdown.
        """
        try:
            await self.start()
            await asyncio.Future() # Keeps the app running
        except Exception as e:
            # logging.error(SerialDeviceMonitor)
            pass
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