from __future__ import annotations

from datetime import datetime, timedelta
import zoneinfo


class TimestampProvider:
    """
    Provides timezone-aware timestamps and second-alignment helpers.

    This class is intentionally stateless so it can be safely instantiated
    wherever needed, such as in AudioManager or WeatherManager.
    """

    def __init__(self, timezone_name: str = "Europe/Bucharest") -> None:
        """
        Initialize the provider with a target timezone.

        Args:
            timezone_name: IANA timezone name used for timestamp generation.

        Raises:
            RuntimeError: If the requested timezone is not available on the system.
        """
        try:
            self.tz = zoneinfo.ZoneInfo(timezone_name)
        except zoneinfo.ZoneInfoNotFoundError as exc:
            raise RuntimeError(
                f"ZoneInfo('{timezone_name}') not available. "
                "Install tzdata on Windows or ensure system tzdata is installed."
            ) from exc

    def now(self) -> datetime:
        """
        Return the current timezone-aware datetime.

        Returns:
            Current datetime in the configured timezone.
        """
        return datetime.now(tz=self.tz)

    def floor_to_second(self, dt: datetime) -> datetime:
        """
        Remove the microseconds part from a datetime.

        Args:
            dt: Datetime to floor.

        Returns:
            The same datetime aligned to the start of its second.
        """
        return dt.replace(microsecond=0)

    def floor_to_minute(self, dt: datetime) -> datetime:
        """
        Floor a datetime to the start of its minute.

        Args:
            dt: Datetime to floor.

        Returns:
            Datetime with seconds and microseconds removed.
        """
        return dt.replace(second=0, microsecond=0)

    def current_second(self) -> datetime:
        """
        Return the current time floored to the current whole second.

        Returns:
            Current datetime with microseconds set to zero.
        """
        return self.floor_to_second(self.now())
    
    def current_minute(self) -> datetime:
        """
        Return the current time floored to the current minute.

        Returns:
            Current datetime aligned to minute precision.
        """
        return self.floor_to_minute(self.now())

    def next_second(self) -> datetime:
        """
        Return the next whole-second boundary.

        Returns:
            Datetime representing the start of the next second.
        """
        return self.current_second() + timedelta(seconds=1)

    def next_minute(self) -> datetime:
        """
        Return the next whole-minute boundary.

        Returns:
            Datetime representing the start of the next minute.
        """
        return self.current_minute() + timedelta(minutes=1)
    
    def previous_minute(self, dt: datetime) -> datetime:
        """
        Return the previous minute bucket for a given datetime.

        Args:
            dt: Reference datetime.

        Returns:
            Datetime aligned to the previous whole minute.
        """
        return self.floor_to_minute(dt) - timedelta(minutes=1)

    def delay_until_next_second(self) -> float:
        """
        Return the delay needed to align execution to the next whole second.

        Returns:
            Number of seconds to sleep until the next second boundary.
        """
        now = self.now()
        next_second = self.floor_to_second(now) + timedelta(seconds=1)
        return max(0.0, (next_second - now).total_seconds())

    def delay_until_next_minute(self) -> float:
        """
        Return the delay needed to align execution to the next whole minute.

        Returns:
            Number of seconds to sleep until the next minute boundary.
        """
        now = self.now()
        next_minute = self.floor_to_minute(now) + timedelta(minutes=1)
        return max(0.0, (next_minute - now).total_seconds())

    def to_mysql_timestamp(self, dt: datetime) -> str:
        """
        Format a datetime for MySQL DATETIME insertion.

        Args:
            dt: Datetime to format.

        Returns:
            Datetime formatted as 'YYYY-MM-DD HH:MM:SS'.
        """
        return dt.strftime("%Y-%m-%d %H:%M:%S")