"""
The follwoing computation are made by using the avaible formulas from
ISO 1996-2 Annex G.
"""

import math
import numpy as np
import asyncio
import logging
import aiomysql

from datetime import timedelta, datetime
from collections import defaultdict

from .value_aggregator import ValueAggregator
from utils.json_config_loader import WeatherConfiguration


class IncertitudeCalculator(ValueAggregator):
    WEATHER_DB_NAME = "weather"

    ACOUSTIC_TO_WEATHER_TABLE = {
        "LAeq1h": "weather1h",
        "LAeq15min": "weather15min",
        "LAeq30min": "weather30min",
    }

    SOURCE_POSITION_TO_DEGREES = {
        "N": 0,
        "E": 90,
        "S": 180,
        "W": 270,
    }

    def __init__(self, param, connection_pool, time_manager, weather_enabled=False):
        super().__init__(param, connection_pool, time_manager)
        self.db_name = param
        self.weather_enabled = weather_enabled
        self.weather_config = WeatherConfiguration()
        self.subscribe_to_intervals(["24h"])
        logging.info("[Incertitude] Subscribed to intervals.")

    async def notifyAboutInterval(self, interval, start_time, end_time):
        """Starts with safety wait of 25 seconds."""

        # Fetch precomputed values
        lday, levening, lnight = await self.fetch_lden_components(
            self.db_name,
            table_name="Lden",
            timestamp=start_time,
        )

        if None in (lday, levening, lnight):
            logging.error("Missing Lden components. Aborting uncertainty computation.")
            return

        use_weather_logic, noise_source_position = self.should_use_weather_logic()
        logging.info(
            f"[Incertitude] Weather logic enabled={use_weather_logic}, "
            f"noise_source_position={noise_source_position}"
        )

        # Current logic remains unchanged for now
        lday_ref, uday_ref = await self.compute_lday_temporal_uncertainty(
            self.db_name,
            start_time,
            end_time,
            lday,
            uncertainty=1,
        )
        levening_ref, uevening_ref = await self.compute_levening_temporal_uncertainty(
            self.db_name,
            start_time,
            end_time,
            levening,
            uncertainty=0.8,
        )
        lnight_ref, unight_ref = await self.compute_lnight_temporal_uncertainty(
            self.db_name,
            start_time,
            end_time,
            lnight,
            uncertainty=0.6,
        )

        # Final U(Lden)
        u_lden = self.compute_lden_uncertainty(
            lday_ref,
            uday_ref,
            levening_ref,
            uevening_ref,
            lnight_ref,
            unight_ref,
        )

        logging.info(f"[Incertitude] U(Lden) = ±{u_lden:.2f} dB")
        await self.insert_aggregated_value(self.db_name, "U_Lden", start_time, u_lden)

    def should_use_weather_logic(self):
        """
        Weather-aware uncertainty should only run when:
        1. weather module is enabled
        2. noise_source_position is present in local weather.json
        """
        if not self.weather_enabled:
            return False, None

        noise_source_position = self.weather_config.get_noise_source_position()
        if noise_source_position is None:
            return False, None

        return True, noise_source_position

    async def fetch_weather_records_with_timestamps(
        self,
        db_name,
        table_name,
        start_time,
        end_time,
    ):
        """
        Fetch weather rows with timestamp, wind_speed, wind_direction.
        """
        records = []

        async with self.connection_pool.acquire() as conn:
            await conn.select_db(db_name)
            async with conn.cursor(aiomysql.DictCursor) as cur:
                fetch_sql = f"""
                SELECT timestamp, wind_speed, wind_direction
                FROM `{table_name}`
                WHERE timestamp >= %s AND timestamp <= %s
                ORDER BY timestamp ASC;
                """
                await cur.execute(fetch_sql, (start_time, end_time))
                rows = await cur.fetchall()

        for row in rows:
            records.append(
                {
                    "timestamp": row["timestamp"],
                    "wind_speed": row["wind_speed"],
                    "wind_direction": row["wind_direction"],
                }
            )

        return records

    async def fetch_acoustic_records_with_timestamps(
        self,
        db_name,
        table_name,
        start_time,
        end_time,
    ):
        """
        Fetch acoustic values together with timestamps.
        """
        records = []

        async with self.connection_pool.acquire() as conn:
            await conn.select_db(db_name)
            async with conn.cursor() as cur:
                fetch_sql = f"""
                SELECT timestamp, value
                FROM `{table_name}`
                WHERE timestamp >= %s AND timestamp <= %s
                ORDER BY timestamp ASC;
                """
                await cur.execute(fetch_sql, (start_time, end_time))
                rows = await cur.fetchall()

        for timestamp, value in rows:
            records.append(
                {
                    "timestamp": timestamp,
                    "value": value,
                }
            )

        return records

    def get_weather_table_for_acoustic_table(self, acoustic_table_name):
        return self.ACOUSTIC_TO_WEATHER_TABLE.get(acoustic_table_name)

    def map_noise_source_position_to_degrees(self, position):
        if position is None:
            return None
        return self.SOURCE_POSITION_TO_DEGREES.get(position)

    def compute_relative_angle(self, source_position, wind_direction):
        """
        Compute absolute angular difference between source direction
        and wind direction, in degrees, normalized to [0, 180].
        """
        source_degrees = self.map_noise_source_position_to_degrees(source_position)

        if source_degrees is None or wind_direction is None:
            return None

        delta = abs(float(wind_direction) - float(source_degrees)) % 360
        return min(delta, 360 - delta)

    def compute_meteorological_indicator(
        self,
        wind_speed,
        wind_direction,
        noise_source_position,
    ):
        """
        First-pass indicator used to classify M1..M4.

        Current implementation:
        - if wind speed is missing -> None
        - if wind speed is very low -> neutral tendency
        - otherwise use a directional factor scaled to [-0.16, 0.16]

        This is intentionally isolated so the final physical formula
        can be replaced later without touching grouping logic.
        """
        if wind_speed is None or wind_direction is None or noise_source_position is None:
            return None

        try:
            wind_speed = float(wind_speed)
            relative_angle = self.compute_relative_angle(
                noise_source_position,
                wind_direction,
            )

            if relative_angle is None:
                return None

            # Calm / nearly calm wind -> treat as neutral
            if wind_speed < 0.5:
                return 0.0

            # Directional component scaled to match M1..M4 threshold range.
            directional_factor = 0.16 * math.cos(math.radians(relative_angle))
            return directional_factor

        except Exception as e:
            logging.error(f"[Incertitude] Failed to compute meteorological indicator: {e}")
            return None

    def classify_meteorological_window(
        self,
        wind_speed,
        wind_direction,
        noise_source_position,
    ):
        """
        Classify interval into M1..M4 based on the indicator thresholds
        from your window table.
        """
        indicator = self.compute_meteorological_indicator(
            wind_speed,
            wind_direction,
            noise_source_position,
        )

        if indicator is None:
            return None

        if indicator <= -0.04:
            return "M1"
        if -0.04 < indicator <= 0.04:
            return "M2"
        if 0.04 < indicator <= 0.12:
            return "M3"
        return "M4"

    def build_meteorological_groups(
        self,
        acoustic_records,
        weather_records,
        noise_source_position,
    ):
        """
        Join acoustic and weather rows by timestamp and group acoustic values
        into M1..M4 buckets.

        Returned structure:
        {
            "M1": [{"timestamp": ..., "value": ..., "wind_speed": ..., "wind_direction": ...}, ...],
            "M2": [...],
            "M3": [...],
            "M4": [...],
        }
        """
        groups = {
            "M1": [],
            "M2": [],
            "M3": [],
            "M4": [],
        }

        weather_by_timestamp = {
            row["timestamp"]: row for row in weather_records
        }

        for acoustic_row in acoustic_records:
            timestamp = acoustic_row["timestamp"]
            acoustic_value = acoustic_row["value"]

            weather_row = weather_by_timestamp.get(timestamp)
            if weather_row is None:
                continue

            window = self.classify_meteorological_window(
                weather_row.get("wind_speed"),
                weather_row.get("wind_direction"),
                noise_source_position,
            )

            if window is None:
                continue

            groups[window].append(
                {
                    "timestamp": timestamp,
                    "value": acoustic_value,
                    "wind_speed": weather_row.get("wind_speed"),
                    "wind_direction": weather_row.get("wind_direction"),
                }
            )

        return groups

    async def build_weather_groups_for_interval(
        self,
        acoustic_db_name,
        acoustic_table_name,
        start_time,
        end_time,
        noise_source_position,
    ):
        """
        Convenience helper:
        - fetch acoustic rows
        - fetch matching weather rows
        - build M1..M4 groups
        """
        weather_table_name = self.get_weather_table_for_acoustic_table(acoustic_table_name)
        if weather_table_name is None:
            logging.warning(
                f"[Incertitude] No weather table mapping found for {acoustic_table_name}"
            )
            return None

        acoustic_records = await self.fetch_acoustic_records_with_timestamps(
            acoustic_db_name,
            acoustic_table_name,
            start_time,
            end_time,
        )

        weather_records = await self.fetch_weather_records_with_timestamps(
            self.WEATHER_DB_NAME,
            weather_table_name,
            start_time,
            end_time,
        )

        groups = self.build_meteorological_groups(
            acoustic_records,
            weather_records,
            noise_source_position,
        )

        logging.info(
            f"[Incertitude] Built meteorological groups for {acoustic_table_name}: "
            f"M1={len(groups['M1'])}, M2={len(groups['M2'])}, "
            f"M3={len(groups['M3'])}, M4={len(groups['M4'])}"
        )

        return groups

    async def compute_lday_temporal_uncertainty(self, db_name, start_time, end_time, lday, uncertainty):
        """
        Entry point for computing U(Lday), with group preparation and final uncertainty logic.
        """
        source_table_name = "LAeq1h"
        GROUP_INTERVALS = {
            "G1_07to10": (7, 10),
            "G2_10to13": (10, 13),
            "G3_13to16": (13, 16),
            "G4_16to19": (16, 19),
        }

        group_datetimes = {
            group: (
                start_time.replace(hour=start_h, minute=0, second=0),
                start_time.replace(hour=end_h, minute=0, second=0)
            )
            for group, (start_h, end_h) in GROUP_INTERVALS.items()
        }

        grouped_result = await self.compute_groups_components(
            db_name,
            source_table_name,
            start_time,
            group_datetimes,
        )

        logging.info(f"{grouped_result}")
        if grouped_result is None or len(grouped_result) < 4:
            logging.warning("[U(Lday)] Not all 4 groups available. Aborting.")
            return None

        lday_ref, uday_ref, _, _ = self.compute_final_uncertainty_interval(
            grouped_result,
            lday,
            uncertainty,
        )

        logging.info(f"[U(Lday)] Final: {lday_ref:.2f} ± {uday_ref:.2f} dB")
        return lday_ref, uday_ref

    async def compute_levening_temporal_uncertainty(self, db_name, start_time, end_time, levening, uncertainty):
        """
        Compute U(Levening) from 15-minute LAeq data grouped in 4 x 1-hour intervals.
        Each group consists of 4 15-minute values.
        """
        source_table_name = "LAeq15min"

        GROUP_INTERVALS = {
            "G1_19to20": (19, 20),
            "G2_20to21": (20, 21),
            "G3_21to22": (21, 22),
            "G4_22to23": (22, 23),
        }

        group_datetimes = {
            name: (
                start_time.replace(hour=start_h, minute=0, second=0),
                start_time.replace(hour=start_h, minute=45, second=0)
            )
            for name, (start_h, end_h) in GROUP_INTERVALS.items()
        }

        grouped_result = await self.compute_groups_components(
            db_name,
            source_table_name,
            start_time,
            group_datetimes,
        )

        if grouped_result is None or len(grouped_result) < 4:
            logging.warning("[U(Levening)] Not all 4 groups available. Aborting.")
            return None

        levening_ref, uevening_ref, _, _ = self.compute_final_uncertainty_interval(
            grouped_result,
            levening,
            uncertainty,
        )
        logging.info(f"[U(Levening)] Final: {levening_ref:.2f} ± {uevening_ref:.2f} dB")

        return levening_ref, uevening_ref

    async def compute_lnight_temporal_uncertainty(self, db_name, start_time, end_time, lnight, uncertainty):
        """
        Entry point for computing U(Lnight), using 4x 2-hour groups with 30-minute LAeq values.
        First group spans across two calendar days (23:00–01:00).
        """
        source_table_name = "LAeq30min"

        group_datetimes = {
            "G1_23to01": (
                (start_time - timedelta(days=1)).replace(hour=23, minute=0, second=0),
                start_time.replace(hour=0, minute=45, second=0)
            ),
            "G2_01to03": (
                start_time.replace(hour=1, minute=0, second=0),
                start_time.replace(hour=2, minute=45, second=0)
            ),
            "G3_03to05": (
                start_time.replace(hour=3, minute=0, second=0),
                start_time.replace(hour=4, minute=45, second=0)
            ),
            "G4_05to07": (
                start_time.replace(hour=5, minute=0, second=0),
                start_time.replace(hour=6, minute=45, second=0)
            ),
        }

        grouped_result = await self.compute_groups_components(
            db_name,
            source_table_name,
            start_time,
            group_datetimes,
        )

        if grouped_result is None or len(grouped_result) < 4:
            logging.warning("[U(Lnight)] Not all 4 groups available. Aborting.")
            return None

        lnight_ref, unight_ref, _, _ = self.compute_final_uncertainty_interval(
            grouped_result,
            lnight,
            uncertainty,
        )

        logging.info(f"[U(Lnight)] Final: {lnight_ref:.2f} ± {unight_ref:.2f} dB")
        return lnight_ref, unight_ref

    async def compute_groups_components(self, db_name, source_table_name, start_time, group_intervals):
        """
        Computes per-group uncertainty details for the Lday, Levening, Lnight uncertainty.
        """
        grouped_result = {}

        for group_name, (group_start, group_end) in group_intervals.items():
            values = await self.fetch_records(db_name, source_table_name, group_start, group_end)
            p_values = await self.fetch_records("LAF", "LAF", group_start, group_end)

            if not values:
                logging.warning(
                    f"Aborting U(Lday): missing data in group {group_name} "
                    f"({group_start} to {group_end})"
                )
                return None

            count = len(values)

            uk, enav = self.compute_group_uncertainty(values, count)
            lres = self.compute_l90_from_group(p_values)
            lk, u_k_prime, ures, cl_prime, cl_res, ulk, weighted_energy = self.compute_expanded_uncertainty(
                enav,
                uk,
                count,
                lres,
            )

            grouped_result[group_name] = {
                "values": values,
                "count": count,
                "enav": enav,
                "lres": lres,
                "lk": lk,
                "u_k_prime": u_k_prime,
                "ures": ures,
                "cl_prime": cl_prime,
                "cl_res": cl_res,
                "ulk": ulk,
                "weighted_energy": weighted_energy,
            }

        return grouped_result

    def compute_final_uncertainty_interval(self, grouped_result, lday, uncertainty):
        """
        Uses per-group uncertainty results to compute U(Lday) and Lday_ref,
        respective for night and evening.
        """
        total_energy = sum(g["weighted_energy"] for g in grouped_result.values())

        for g in grouped_result.values():
            g["cl"] = g["weighted_energy"] / total_energy

        for g in grouped_result.values():
            g["lk_energy"] = 10 ** (0.1 * g["lk"])

        log_factor = 10 * math.log10(2.7)

        for g in grouped_result.values():
            g["cp"] = log_factor * (g["lk_energy"] / total_energy)

        upi = 0.05
        u_weight = math.sqrt(
            sum((g["ulk"] ** 2) * (g["cl"] ** 2) for g in grouped_result.values()) +
            sum((g["cp"] ** 2) * (upi ** 2) for g in grouped_result.values())
        )

        l_ref = lday + uncertainty
        u_ref = math.sqrt(u_weight ** 2 + 0.2 ** 2)

        return l_ref, u_ref, u_weight, grouped_result

    @staticmethod
    def compute_group_uncertainty(values, count):
        """
        Computes the uncertainity for a group of LAEQ values.
        """
        if count < 2:
            return 0.0, None

        energies = [10 ** (0.1 * v) for v in values]
        e_bar = sum(energies) / count
        enav = 10 * math.log10(e_bar)

        enav_energy = 10 ** (0.1 * enav)
        squared_diffs = [(10 ** (0.1 * v) - enav_energy) ** 2 for v in values]

        sk = math.sqrt(sum(squared_diffs) / (count - 1))
        uk = 10 * math.log10(enav_energy + sk) - enav

        return uk, enav

    @staticmethod
    def compute_l90_from_group(values):
        """
        Computes L90 (the 90th percentile) from a list of LAF values.
        This approximates background noise level (Lres).
        """
        if not values:
            return None

        values = np.array(values, dtype=float)
        values = values[np.isfinite(values)]
        if len(values) == 0:
            return None

        p_values = np.percentile(values, 10)
        return round(p_values, 2)

    @staticmethod
    def compute_expanded_uncertainty(enav, uk, count, lres):
        """
        Computes uLk — the expanded uncertainty of corrected Lk level.
        """
        if count < 2:
            return None

        u_k_prime = uk / math.sqrt(count)
        ures = 4 / math.sqrt(count)

        if enav - lres < 3:
            lk = enav
            cl_prime = 1.0
            cl_res = 0.0
            ulk = u_k_prime
            logging.warning(
                f"[ISO 1996-2] enav - lres < 3 dB → skipping background correction. "
                f"Using Lk = enav = {lk:.2f} dB"
            )
        else:
            linear_diff = 10 ** (0.1 * enav) - 10 ** (0.1 * lres)
            if linear_diff <= 0:
                logging.error(
                    f"Invalid linear diff: 10^enav - 10^lres = {linear_diff} | "
                    f"enav={enav}, lres={lres}"
                )
                return None

            lk = 10 * math.log10(linear_diff)

            denom = 1 - 10 ** (-0.1 * (enav - lres))
            if abs(denom) < 1e-6:
                logging.error(
                    f"Denominator too small in cL' computation: enav={enav}, lres={lres}"
                )
                return None

            cl_prime = 1 / denom
            cl_res = cl_prime * 10 ** (-0.1 * (enav - lres))

            inner = (cl_prime ** 2) * (u_k_prime ** 2) + (cl_res ** 2) * (ures ** 2)
            if inner < 0:
                logging.error(f"Negative sqrt argument for uLk: {inner}")
                return None

            ulk = math.sqrt(inner)

        weighted_energy = 10 ** (0.1 * lk) * 0.25
        return lk, u_k_prime, ures, cl_prime, cl_res, ulk, weighted_energy

    @staticmethod
    def compute_lden_uncertainty(lday_ref, uday_ref, levening_ref, uevening_ref, lnight_ref, unight_ref):
        """
        Computes combined expanded uncertainty U(Lden) based on uncertainties
        from Lday, Levening, and Lnight components using energy weighting.
        """
        A = 12 * 10 ** (0.1 * lday_ref)
        B = 4 * 10 ** (0.1 * (levening_ref + 5))
        C = 8 * 10 ** (0.1 * (lnight_ref + 10))

        numerator = math.sqrt(
            (A ** 2) * (uday_ref ** 2) +
            (B ** 2) * (uevening_ref ** 2) +
            (C ** 2) * (unight_ref ** 2)
        )

        denominator = A + B + C
        u_lden = numerator / denominator
        return round(u_lden, 2)

    async def fetch_lden_components(self, db_name, table_name, timestamp):
        """
        Fetch lday_eu, levening_eu, lnight_eu from the latest Lden row for a given timestamp.
        """
        async with self.connection_pool.acquire() as conn:
            await conn.select_db(db_name)
            async with conn.cursor() as cur:
                fetch_sql = f"""
                SELECT lday_eu, levening_eu, lnight_eu
                FROM `{table_name}`
                WHERE timestamp = %s
                LIMIT 1;
                """
                await cur.execute(fetch_sql, (timestamp,))
                row = await cur.fetchone()

                if row is None:
                    logging.error(f"[Incertitude] No Lden data found for timestamp {timestamp}")
                    return None, None, None

                return row[0], row[1], row[2]

    async def aggregate(self):
        pass