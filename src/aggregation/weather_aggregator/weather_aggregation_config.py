AGGREGATION_RULES = {
    "out_temp": "avg",
    "out_humi": "avg",
    "wind_speed": "avg",
    "wind_direction": "circular_mean",
    "solar_radiation": "avg",
    "in_temp": "avg",
    "in_humi": "avg",
    "in_abs_pressure": "avg",
    "in_rel_pressure": "avg",
    "rain_event": "sum",
    "rain_rate": "avg",
    "is_raining": "max",
}

TARGET_TABLES = {
    "5min": "weather5min",
    "15min": "weather15min",
    "30min": "weather30min",
    "1h": "weather1h",
    "24h": "weather24h",
}

COLUMN_TYPES = {
    "out_temp": "FLOAT NULL",
    "out_humi": "INT NULL",
    "wind_speed": "FLOAT NULL",
    "wind_direction": "INT NULL",
    "solar_radiation": "FLOAT NULL",
    "in_temp": "FLOAT NULL",
    "in_humi": "INT NULL",
    "in_abs_pressure": "FLOAT NULL",
    "in_rel_pressure": "FLOAT NULL",
    "rain_event": "FLOAT NULL",
    "rain_rate": "FLOAT NULL",
    "is_raining": "TINYINT(1) NULL",
}