import logging


def build_expected_timestamps(start_interval, end_interval, step):
    timestamps = []
    current = start_interval
    while current < end_interval:
        timestamps.append(current)
        current += step
    return timestamps

def get_signed_wind_speed(noise_source_position, wind_direction, wind_speed):
    if noise_source_position == "N":
        if 135 <= wind_direction <= 225:
            return -wind_speed
        return wind_speed

    if noise_source_position == "S":
        if wind_direction >= 315 or wind_direction <= 45:
            return -wind_speed
        return wind_speed

    if noise_source_position == "E":
        if 225 <= wind_direction <= 315:
            return -wind_speed
        return wind_speed

    if noise_source_position == "W":
        if 45 <= wind_direction <= 135:
            return -wind_speed
        return wind_speed

    return None

def classify_meteo_window(signed_wind_speed, period):
    if period in ("day", "evening"):
        if signed_wind_speed < 1:
            return "M1"
        elif signed_wind_speed < 3:
            return "M2"
        elif signed_wind_speed < 6:
            return "M3"
        else:
            return "M4"

    if period == "night":
        if signed_wind_speed < -1:
            return "M1"
        else:
            return "M4"

    return None

def build_empty_groups(period):
    if period in ("day", "evening"):
        return {
            "M1": {"values": [], "timestamps": []},
            "M2": {"values": [], "timestamps": []},
            "M3": {"values": [], "timestamps": []},
            "M4": {"values": [], "timestamps": []},
        }

    if period == "night":
        return {
            "M1": {"values": [], "timestamps": []},
            "M4": {"values": [], "timestamps": []},
        }

    return {}


def group_values_by_weather_window(acoustic_map, weather_map, expected_timestamps, noise_source_position, period):
    groups = build_empty_groups(period)

    for ts in expected_timestamps:
        if ts not in acoustic_map:
            logging.warning(f"[WeatherIncertitude] Missing acoustic value at {ts}")
            return None

        if ts not in weather_map:
            logging.warning(f"[WeatherIncertitude] Missing weather value at {ts}")
            return None

        value = acoustic_map[ts]
        wind_speed, wind_direction = weather_map[ts]

        signed_wind_speed = get_signed_wind_speed(noise_source_position, wind_direction, wind_speed)
        if signed_wind_speed is None:
            logging.warning(f"[WeatherIncertitude] Invalid wind data at {ts}")
            return None

        window = classify_meteo_window(signed_wind_speed, period)
        if window is None:
            logging.warning(f"[WeatherIncertitude] Could not classify window at {ts}")
            return None

        groups[window].append(value)
        groups[window]["timestamps"].append(ts)

    return groups