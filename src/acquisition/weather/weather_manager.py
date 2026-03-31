from __future__ import annotations

import asyncio
import logging

from asyncio import Task

from database.mysql.mysql_connection_manager import MySQLConnectionManager

from .weather_client import WeatherClient
from .weather_poller import WeatherPoller
from acquisition.help_functions.timestamp_provider import TimestampProvider


class WeatherManager:
    def __init__(
        self,
        device_ip: str,
        mysql_manager: MySQLConnectionManager,
    ) -> None:
        self.device_ip: str = device_ip
        self.mysql_manager: MySQLConnectionManager = mysql_manager

        self.client: WeatherClient | None = None
        self.poller: WeatherPoller | None = None
        self.poller_task: Task[None] | None = None

        self.timestamp_provider: TimestampProvider = TimestampProvider()

    async def start(self) -> None:
        logging.info("Weather manager started")

        self.client = WeatherClient(device_ip=self.device_ip)

        self.poller = WeatherPoller(
            client=self.client,
            mysql_pool=self.mysql_manager.pool,
            timestamp_provider=self.timestamp_provider,
        )

        self.poller_task = asyncio.create_task(
            self.poller.start(),
            name="weather-poller-task",
        )

    async def stop(self) -> None:
        if self.poller:
            await self.poller.stop()
            await self.client.close()

        if self.poller_task:
            self.poller_task.cancel()
            try:
                await self.poller_task
            except asyncio.CancelledError:
                logging.info("Weather poller task cancelled")

        logging.info("Weather manager stopped")