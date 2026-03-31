from __future__ import annotations


DEVICE_INFO_FIELDS: dict[str, dict[str, dict[str, dict[str, str]]]] = {
    "piezoRain": {
        "0x13": {
            "battery": {"column": "battery", "unit": "level"},
            "voltage": {"column": "voltage", "unit": "V"},
        },
    },
}