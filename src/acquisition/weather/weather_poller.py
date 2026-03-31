from __future__ import annotations

import aiomysql
import asyncio
import logging

from datetime import datetime
from contextlib import asynccontextmanager
from typing import Any


from acquisition.help_functions.timestamp_provider import TimestampProvider
from .weather_client import WeatherClient
from utils.env_config_loader import Config

class WeatherPoller:
    def __init__(
        self,
        client: WeatherClient,
        mysql_pool: aiomysql.Pool,
        timestamp_provider: TimestampProvider,
    ) -> None:
        self.client = client
        self.mysql_pool = mysql_pool
        self.timestamp_provider = timestamp_provider


        self.db_manager = DatabaseManagerWeather(self.mysql_pool)

        self._running: bool = False

    async def start(self) -> None:
        logging.info("Weather poller started")

        # Initialize database
        await self.db_manager.initialize()

        self._running = True

        try:
            await self._fetch_and_store_weather_data()

            while self._running:
                delay = self.timestamp_provider.delay_until_next_minute()
                logging.info(f"Waiting {delay:.3f} seconds until next minute boundary")
                await asyncio.sleep(delay)

                if not self._running:
                    break

                logging.info("Polling weather data")
                await self._fetch_and_store_weather_data()

        except asyncio.CancelledError:
            logging.info("Weather poller cancelled")
            raise

        finally:
            logging.info("Weather poller stopped")

    async def _fetch_and_store_weather_data(self) -> None:
        fetch_time: datetime = self.timestamp_provider.now()
        save_time: datetime = self.timestamp_provider.previous_minute(fetch_time)

        logging.info(
            f"Fetching weather data | fetch_time={fetch_time.isoformat(timespec='seconds')} "
            f"| save_time={save_time.isoformat(timespec='seconds')}"
        )

        weather_data: dict[str, Any] | None = await self._fetch_weather_data()

        if weather_data is None:
            logging.warning(
                f"No weather data returned for minute "
                f"{save_time.isoformat(timespec='seconds')}"
            )
            return

        await self._insert_weather_data(
            weather_data=weather_data,
            save_time=save_time,
        )

    async def _fetch_weather_data(self) -> dict[str, Any] | None:
        return await self.client.get_weather_minute_data()

    async def _insert_weather_data(
        self,
        weather_data: dict[str, Any],
        save_time: datetime,
    ) -> None:
        mysql_timestamp = self.timestamp_provider.to_mysql_timestamp(save_time)

        logging.info(f"Storing weather data in MySQL | save_time={mysql_timestamp} and {weather_data}")

        await self.db_manager.insert_weather1min(
            timestamp=mysql_timestamp,
            weather_data=weather_data,
        )

    async def stop(self) -> None:
        logging.info("Stopping weather poller...")
        self._running = False
    


class DatabaseManagerWeather:
    
    def __init__(self, connection_pool: aiomysql.Pool) -> None:
        self.pool: aiomysql.Pool = connection_pool
        self.database_name : str = "weather"
        self.table_name: str = "weather1min" 
        self.data_retention_days: int = Config.MYSQL_DATA_RETENTION

    @asynccontextmanager
    async def get_connection(self, db_name: str | None = None):
        async with self.pool.acquire() as conn:
            if db_name:
                await conn.select_db(db_name)

            async with conn.cursor(aiomysql.DictCursor) as cur:
                yield conn, cur
    
    async def initialize(self) -> None:
        await self.create_database()
        async with self.get_connection(db_name=self.database_name) as (conn, cur):
            await self._create_weather1min_table_if_not_exists(conn, cur)
        
    async def create_database(self) -> None:
        async with self.get_connection() as (conn, cur):
            await cur.execute(f"CREATE DATABASE IF NOT EXISTS `{self.database_name}`;")
            await conn.commit()


    async def _create_weather1min_table_if_not_exists(
        self,
        conn: aiomysql.Connection,
        cur: Any,
    ) -> None:
        create_table_sql = f"""
        CREATE TABLE IF NOT EXISTS `{self.table_name}` (
            id INT PRIMARY KEY AUTO_INCREMENT,
            timestamp TIMESTAMP NOT NULL,

            out_temp FLOAT NULL,
            out_humi INT NULL,
            feels_like FLOAT NULL,
            vpd FLOAT NULL,
            dew_point FLOAT NULL,
            wind_speed FLOAT NULL,
            gust_speed FLOAT NULL,
            solar_radiation FLOAT NULL,
            uvi INT NULL,
            wind_direction INT NULL,
            wind_direction_label VARCHAR(4) NULL,

            in_temp FLOAT NULL,
            in_humi INT NULL,
            in_abs_pressure FLOAT NULL,
            in_rel_pressure FLOAT NULL,

            is_raining TINYINT(1) NULL,
            rain_event FLOAT NULL,
            rain_rate FLOAT NULL,

            is_sent TINYINT NOT NULL DEFAULT 0,
            is_aggregated TINYINT NOT NULL DEFAULT 0,

            INDEX idx_timestamp (timestamp),
            INDEX idx_is_sent (is_sent),
            INDEX idx_is_aggregated (is_aggregated),
            INDEX idx_is_sent_is_aggregated (is_sent, is_aggregated)
        );
        """
        await cur.execute(create_table_sql)

        create_event_sql = f"""
        CREATE EVENT IF NOT EXISTS `ev_delete_old_data_{self.table_name}`
        ON SCHEDULE EVERY 1 DAY
        DO
            DELETE FROM `{self.table_name}`
            WHERE timestamp < NOW() - INTERVAL {self.data_retention_days} DAY;
        """
        await cur.execute(create_event_sql)

        await conn.commit()

    async def insert_weather1min(
        self,
        timestamp: str,
        weather_data: dict[str, Any],
    ) -> None:
        if not weather_data:
            logging.warning("No weather data provided for insert into weather1min.")
            return

        columns = ["timestamp", *weather_data.keys(), "is_sent", "is_aggregated"]
        placeholders = ", ".join(["%s"] * len(columns))
        column_sql = ", ".join(f"`{column}`" for column in columns)

        values = [timestamp, *weather_data.values(), 0, 0]

        insert_sql = f"""
        INSERT INTO `{self.table_name}` ({column_sql})
        VALUES ({placeholders});
        """

        async with self.get_connection(db_name=self.database_name) as (conn, cur):
            await cur.execute(insert_sql, values)
            await conn.commit()