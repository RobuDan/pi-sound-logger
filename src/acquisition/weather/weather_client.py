from __future__ import annotations

from typing import Any

import aiohttp
import asyncio
import logging

from .mappings.weather_minute import WEATHER_MINUTE_FIELDS
from .mappings.weather_cumulative import WEATHER_CUMULATIVE_FIELDS
from .mappings.device_info import DEVICE_INFO_FIELDS


class WeatherClient:
    def __init__(self, device_ip: str) -> None:
        self.device_ip: str = device_ip

        self.weather_minute_fields: dict[str, Any] = WEATHER_MINUTE_FIELDS
        self.weather_cumulative_fields: dict[str, Any] = WEATHER_CUMULATIVE_FIELDS
        self.device_info_fields: dict[str, Any] = DEVICE_INFO_FIELDS

        self.session: aiohttp.ClientSession | None = None

    def _build_livedata_url(self) -> str:
        return f"http://{self.device_ip}/get_livedata_info"

    async def _get_session(self) -> aiohttp.ClientSession:
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()
        return self.session

    async def _get_livedata_info(self) -> dict[str, Any] | None:
        url = self._build_livedata_url()

        try:
            session = await self._get_session()

            async with session.get(url) as response:
                response.raise_for_status()
                return await response.json()

        except asyncio.TimeoutError:
            logging.error(f"Weather API request timed out for {url}")
            return None

        except aiohttp.ClientError as exc:
            logging.error(f"Weather API request failed for {url}: {exc}")
            return None

        except Exception as exc:
            logging.error(f"Unexpected weather API error for {url}: {exc}")
            return None
            

    async def get_weather_minute_data(self) -> dict[str, Any] | None:
        livedata = await self._get_livedata_info()
        if livedata is None:
            return None
        raw = self._extract_fields(livedata, self.weather_minute_fields)
        normalized = self._normalize_data(raw)
        enriched = self._enrich_data(normalized)
        return enriched

    async def get_weather_cumulative_data(self) -> dict[str, Any]:
        livedata = await self._get_livedata_info()
        if livedata is None:
            return None
        
        raw =  self._extract_fields(livedata, self.weather_cumulative_fields)
        return self._normalize_data(raw)
    
    async def get_device_info(self) -> dict[str, Any]:
        livedata = await self._get_livedata_info()
        if livedata is None:
            return None
        
        raw =  self._extract_fields(livedata, self.device_info_fields)
        return self._normalize_data(raw)
    
    def _extract_fields(
        self,
        livedata: dict[str, Any],
        mapping: dict[str, Any],
    ) -> dict[str, Any]:
        extracted_data: dict[str, Any] = {}

        for section_name, section_mapping in mapping.items():
            section_data = livedata.get(section_name)

            if not isinstance(section_data, list) or not section_data:
                continue

            if section_name in {"common_list", "piezoRain"}:
                for item in section_data:
                    if not isinstance(item, dict):
                        continue

                    item_id = item.get("id")
                    if item_id not in section_mapping:
                        continue

                    field_mapping = section_mapping[item_id]

                    # normal id -> val mapping
                    if "column" in field_mapping:
                        column_name = field_mapping["column"]
                        extracted_data[column_name] = item.get("val")
                        continue

                    # id -> nested field mapping
                    for raw_key, field_info in field_mapping.items():
                        if raw_key not in item:
                            continue

                        column_name = field_info["column"]
                        extracted_data[column_name] = item[raw_key]

            else:
                first_item = section_data[0]
                if not isinstance(first_item, dict):
                    continue

                for raw_key, field_info in section_mapping.items():
                    if raw_key not in first_item:
                        continue

                    column_name = field_info["column"]
                    extracted_data[column_name] = first_item[raw_key]

        return extracted_data
    
    def _normalize_value(self, value: str) -> float | int | None:
        if not isinstance(value, str):
            return None
        
        value = value.strip()
        if not value:
            return None

        # Case: "1.18 kPa", "0.0 m/s"
        if " " in value:
            value = value.split(" ")[0]
        
        # Case: "53%"
        if value.endswith("%"):
            value = value[:-1]

        try:
            return int(value)
        except ValueError:
            pass
        
        try:
            return float(value)
        except ValueError:
            return None

    def _normalize_data(self, data: dict[str, Any]) -> dict[str, float | int | None]:
        normalized = {}

        for key, value in data.items():
            normalized[key] = self._normalize_value(value)

        return normalized

    def _degrees_to_compass(self, degrees: int) -> str | None:
        if degrees is None:
            return None
        
        directions = [
        "N", "NNE", "NE", "ENE",
        "E", "ESE", "SE", "SSE",
        "S", "SSW", "SW", "WSW",
        "W", "WNW", "NW", "NNW",
        ]

        index = int((degrees + 11.25) // 22.5) % 16
        return directions[index]
    
    def _enrich_data(self, data: dict[str, Any]) -> dict[str, Any]:
        wind_deg = data.get("wind_direction")

        if isinstance(wind_deg, int):
            data["wind_direction_label"] = self._degrees_to_compass(wind_deg)
        else:
            data["wind_direction_label"] = None

        return data

    async def close(self) -> None:
        if self.session and not self.session.closed:
            await self.session.close()