from __future__ import annotations

from .livedata_sources import COMMON_LIST_FIELD_MAP, PIEZO_RAIN_FIELD_MAP


WEATHER_CUMULATIVE_FIELDS: dict[str, dict[str, dict[str, str]]] = {
    "common_list": {
        "0x19": COMMON_LIST_FIELD_MAP["0x19"],
    },
    "piezoRain": {
        "0x10": PIEZO_RAIN_FIELD_MAP["0x10"],
        "0x11": PIEZO_RAIN_FIELD_MAP["0x11"],
        "0x12": PIEZO_RAIN_FIELD_MAP["0x12"],
        "0x13": PIEZO_RAIN_FIELD_MAP["0x13"],
    },
}