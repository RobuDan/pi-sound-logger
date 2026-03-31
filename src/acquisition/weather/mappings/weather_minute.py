from __future__ import annotations

from .livedata_sources import (
    COMMON_LIST_FIELD_MAP,
    PIEZO_RAIN_FIELD_MAP,
    WH25_FIELD_MAP,
)


WEATHER_MINUTE_FIELDS: dict[str, dict[str, dict[str, str]]] = {
    "common_list": {
        "0x02": COMMON_LIST_FIELD_MAP["0x02"],
        "0x07": COMMON_LIST_FIELD_MAP["0x07"],
        "3": COMMON_LIST_FIELD_MAP["3"],
        "5": COMMON_LIST_FIELD_MAP["5"],
        "0x03": COMMON_LIST_FIELD_MAP["0x03"],
        "0x0B": COMMON_LIST_FIELD_MAP["0x0B"],
        "0x0C": COMMON_LIST_FIELD_MAP["0x0C"],
        "0x15": COMMON_LIST_FIELD_MAP["0x15"],
        "0x17": COMMON_LIST_FIELD_MAP["0x17"],
        "0x0A": COMMON_LIST_FIELD_MAP["0x0A"],
    },
    "wh25": {
        "intemp": WH25_FIELD_MAP["intemp"],
        "inhumi": WH25_FIELD_MAP["inhumi"],
        "abs": WH25_FIELD_MAP["abs"],
        "rel": WH25_FIELD_MAP["rel"],
    },
    "piezoRain": {
        "srain_piezo": PIEZO_RAIN_FIELD_MAP["srain_piezo"],
        "0x0D": PIEZO_RAIN_FIELD_MAP["0x0D"],
        "0x0E": PIEZO_RAIN_FIELD_MAP["0x0E"],
    },
}