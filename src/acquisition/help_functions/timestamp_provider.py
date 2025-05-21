from datetime import datetime
import zoneinfo

class TimestampProvider:
    """
    Provides timezone-aware UTC+2 timestamps in Europe/Bucharest.
    Handles daylight saving time automatically.
    Optionally provides aligned start time and sleep calculation for sync.
    """

    def __init__(self):
        try:
            self.tz = zoneinfo.ZoneInfo("Europe/Bucharest")
        except zoneinfo.ZoneInfoNotFoundError:
            raise RuntimeError(
                "ZoneInfo('Europe/Bucharest') not available.\n"
                "Run `pip install tzdata` on Windows or ensure system tzdata is installed."
            )
        self.start_timestamp = None

    def initialize(self):
        """Call once at the start of acquisition to mark aligned start."""
        if self.start_timestamp is None:
            now = datetime.now(tz=self.tz)
            self.start_timestamp = now.replace(microsecond=0)

    def get_timestamp(self) -> datetime:
        """
        Get current timezone-aware timestamp (Europe/Bucharest).
        Returns:
            datetime: Current timestamp with tzinfo.
        """
        return datetime.now(tz=self.tz)

    def get_start_timestamp(self) -> datetime:
        """
        Get the acquisition-aligned timestamp.
        Returns:
            datetime: Start timestamp (or None if not initialized).
        """
        return self.start_timestamp

    def get_next_second_sleep_time(self) -> float:
        """
        Get delay (in seconds) needed to sleep until next full second.
        Returns:
            float: Time to sleep until sec:000.
        """
        now = self.get_timestamp().timestamp()
        return 1.0 - (now % 1.0)
