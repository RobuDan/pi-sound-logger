import asyncio
import logging
import nsrt_mk3_dev

from aggregation.aggregation_manager import AggregationManager
from utils.json_config_loader import LoadConfiguration
from .acoustic_stream import AcousticStream
from .audio_stream import AudioStream
from .help_functions.timestamp_provider import TimestampProvider


class AcquisitionManager:
    """
    Coordinates the initialization and management of acoustic data acquisition.

    Responsibilities:
    - Load configuration from JSON
    - Connect to the NSRT device over serial
    - Apply device settings (tau, weighting, fs)
    - Start acoustic (and future audio) data streams
    - Cleanly stop all tasks on shutdown
    """

    def __init__(self, device, mysql_manager):
        """
        Initialize internal components, placeholders, and device-specific defaults.
        """
        self.device =device
        self.mysql_manager = mysql_manager

        self.parameters = None
        self.agconfig = None

        self.acoustic_stream = None
        self.audio_stream = None
        self.spectrum_stream = None  # Will not be targeted for this type of device
        self.agmanager = None  

        # Device defaults
        self.fs = 48000              # Fixed sampling rate
        self.tau = 0.125             # Time constant (sec)
        self.weighting = "A"         # Default dB weighting (can be "C" or "Z")
        self.timestamp_provider = TimestampProvider  # Initialized in manager_start()

    async def start(self):
        """
        Entry point for full initialization and stream startup.
        """
        # Load parameters and aggregation config from disk
        loader = LoadConfiguration()
        self.parameters, self.agconfig = loader.load_config("config/parameters.json")
        self.weighting = self.parameters.get("Weighting", "A")

        # Setup serial-connected NSRT device
        await self.initialize_device()

        # Setup wall-clock time reference for synchronization
        self.timestamp_provider = TimestampProvider()
        self.timestamp_provider.initialize()

        # Start data agregation manager 
        self.agmanager = AggregationManager(self.agconfig, self.mysql_manager.pool)
        await self.agmanager.start()
        # Launch selected streams
        await self.start_handle_acquisition()

    async def initialize_device(self):
        """
        Connects to the NSRT device and applies core configuration.
        """

        if not self.device.write_tau(self.tau):
            raise RuntimeError(f"Failed to set tau to {self.tau}s")

        await self.enforce_weighting()

        current_fs = self.device.read_fs()
        if current_fs != self.fs:
            if not self.device.write_fs(self.fs):
                raise RuntimeError(f"Failed to set sampling frequency to {self.fs} Hz")

        logging.info(f"Device configured: weighting={self.weighting}, tau={self.tau}, fs={self.fs}")

    async def enforce_weighting(self):
        """
        Verifies or sets the device's dB weighting (A, C, Z).
        """
        current = self.device.read_weighting().name        # e.g., "DB_A"
        expected = f"DB_{self.weighting}"                 # -> "DB_A"

        if current != expected:
            logging.info(f"Setting device weighting to {expected}")
            enum_expected = self.device.Weighting[expected]  # Convert to enum
            success = self.device.write_weighting(enum_expected)
            if not success:
                raise RuntimeError(f"Failed to set weighting to {self.weighting}")

    async def start_handle_acquisition(self):
        """
        Instantiates and starts selected data streams: acoustic (and optionally audio).
        """
        if self.parameters.get("AcousticSequences"):
            self.acoustic_stream = AcousticStream(
                self.device,
                self.parameters["AcousticSequences"],
                self.mysql_manager.pool,
                sample_interval=self.tau,
                timestamp_provider=self.timestamp_provider
            )
            logging.info("AcousticStream ready.")

        if self.parameters.get("AudioSequences"):
            audio_seq = int(self.parameters["AudioSequences"][0])
            self.audio_stream = AudioStream(
                sample_rate=self.fs,
                timestamp_provider=self.timestamp_provider)
            logging.info("AudioStream ready.")

        tasks = []
        if self.acoustic_stream:
            tasks.append(self.acoustic_stream.start())
        if self.audio_stream:
            tasks.append(self.audio_stream.start())

        if tasks:
            await asyncio.gather(*tasks)


    async def cleanup_streams(self):
        """
        Gracefully stops active streams and logs any errors.
        """
        tasks = []
        if self.acoustic_stream:
            tasks.append(self.acoustic_stream.cleanup())
        if self.audio_stream:
            tasks.append(self.audio_stream.cleanup())

        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for result, task in zip(results, tasks):
                if isinstance(result, Exception):
                    logging.error(f"Error stopping {task}: {result}")
                else:
                    logging.info(f"{task} stopped successfully.")

    async def stop(self):
        """
        Stops the full acquisition manager and its subcomponents.
        """

        await self.agmanager.stop()
        await self.cleanup_streams()
        logging.info("AcquisitionManager stopped.")
