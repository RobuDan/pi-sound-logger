from __future__ import annotations


COMMON_LIST_FIELD_MAP: dict[str, dict[str, str]] = {
    "0x02": {"column": "out_temp", "unit": "C"},
    "0x07": {"column": "out_humi", "unit": "%"},
    "3": {"column": "feels_like", "unit": "C"},
    "5": {"column": "vpd", "unit": "kPa"},
    "0x03": {"column": "dew_point", "unit": "C"},
    "0x0B": {"column": "wind_speed", "unit": "m/s"},
    "0x0C": {"column": "gust_speed", "unit": "m/s"},
    "0x19": {"column": "day_max_wind", "unit": "m/s"},
    "0x15": {"column": "solar_radiation", "unit": "W/m2"},
    "0x17": {"column": "uvi", "unit": "index"},
    "0x0A": {"column": "wind_direction", "unit": "deg"},
}

WH25_FIELD_MAP: dict[str, dict[str, str]] = {
    "intemp": {"column": "in_temp", "unit": "C"},
    "inhumi": {"column": "in_humi", "unit": "%"},
    "abs": {"column": "in_abs_pressure", "unit": "hPa"},
    "rel": {"column": "in_rel_pressure", "unit": "hPa"},
}

PIEZO_RAIN_FIELD_MAP: dict[str, dict[str, str]] = {
    "srain_piezo": {"column": "is_raining", "unit": "bool"},
    "0x0D": {"column": "rain_event", "unit": "mm"},
    "0x0E": {"column": "rain_rate", "unit": "mm/h"},
    "0x10": {"column": "rain_day", "unit": "mm"},
    "0x11": {"column": "rain_week", "unit": "mm"},
    "0x12": {"column": "rain_month", "unit": "mm"},
    "0x13": {"column": "rain_year", "unit": "mm"},
}