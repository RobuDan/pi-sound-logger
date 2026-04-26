import logging
import math
import numpy as np
from datetime import timedelta

from .help_functions.queries import fetch_acoustic_data, fetch_weather_data, fetch_laf_data
from .help_functions.weather_windows import build_expected_timestamps, group_values_by_weather_window


class WeatherUncertaintyCalculator:
    def __init__(self, acoustic_db_name, connection_pool, start_time, end_time, noise_source_position):
        self.acoustic_db_name = acoustic_db_name
        self.weather_db_name = "weather"
        self.connection_pool = connection_pool
        self.start_time = start_time
        self.end_time = end_time
        self.noise_source_position = noise_source_position

    async def compute_weather_uncertainty(self):
        lday, lday_ref, uday_ref = await self.compute_lday_temporal_uncertainty(uncertainty=1)
        logging.info(f"[WeatherUncertainty] Lday result: lday_ref={lday_ref}, uday_ref={uday_ref}")

        levening, levening_ref, uevening_ref = await self.compute_levening_temporal_uncertainty(uncertainty=0.8)
        logging.info(f"[WeatherUncertainty] Levening result: levening_ref={levening_ref}, uevening_ref={uevening_ref}")

        lnight, lnight_ref, unight_ref = await self.compute_lnight_temporal_uncertainty(uncertainty=0.6)
        logging.info(f"[WeatherUncertainty] Lnight result: lnight_ref={lnight_ref}, unight_ref={unight_ref}")

        if None in (
            lday, lday_ref, uday_ref,
            levening, levening_ref, uevening_ref,
            lnight, lnight_ref, unight_ref,
        ):
            logging.warning("[WeatherUncertainty] Aborting final weather result: one or more period results are missing.")
            return None

        return (
            lday, lday_ref, uday_ref,
            levening, levening_ref, uevening_ref,
            lnight, lnight_ref, unight_ref,
        )
    
    async def compute_lday_temporal_uncertainty(self, uncertainty=1):
        source_acoustic_table = "LAeq1h"
        source_weather_table = "weather1h"
        step = timedelta(hours=1)
        period = "day"

        start_interval = self.start_time.replace(hour=7, minute=0, second=0)
        end_interval = self.start_time.replace(hour=19, minute=0, second=0)

        acoustic_map, weather_map, expected_timestamps = await self.fetch_interval_data(source_acoustic_table, source_weather_table, start_interval, end_interval, step)

        groups = group_values_by_weather_window(acoustic_map, weather_map, expected_timestamps, self.noise_source_position, period)
        if groups is None:
            logging.warning("[WeatherUncertainty] Aborting Lday: missing acoustic/weather data or invalid window classification.")
            return None, None, None

        logging.info(
            f"[WeatherUncertainty][{period}] Grouped values summary: "
            f"{ {k: {'count': len(v['values']), 'timestamps': v['timestamps']} for k, v in groups.items()} }"
        )

        grouped_result = await self.compute_group_components(groups, period, step, total_expected_count=12)
        if grouped_result is None:
            logging.warning("[WeatherUncertainty] Aborting Lday: could not compute grouped result.")
            return None, None, None

        logging.info(f"Lday group: {grouped_result}")

        lday = 10 * math.log10(sum(g["weighted_energy"] for g in grouped_result.values()))
        logging.info(f"[WeatherUncertainty][{period}] Computed lday from grouped energies: lday={round(lday, 2)}")
        
        lday_ref, uday_ref, _, _ = self.compute_final_uncertainty_interval(grouped_result, lday, uncertainty)
        return lday, lday_ref, uday_ref

    async def compute_levening_temporal_uncertainty(self, uncertainty=0.8):
        source_acoustic_table = "LAeq15min"
        source_weather_table = "weather15min"
        step = timedelta(minutes=15)
        period = "evening"

        start_interval = self.start_time.replace(hour=19, minute=0, second=0)
        end_interval = self.start_time.replace(hour=23, minute=0, second=0)

        acoustic_map, weather_map, expected_timestamps = await self.fetch_interval_data(source_acoustic_table, source_weather_table, start_interval, end_interval, step)
        
        groups = group_values_by_weather_window(acoustic_map, weather_map, expected_timestamps, self.noise_source_position, period)
        if groups is None:
            logging.warning("[WeatherUncertainty] Aborting Levening: missing acoustic/weather data or invalid window classification.")
            return None, None, None

        logging.info(
            f"[WeatherUncertainty][{period}] Grouped values summary: "
            f"{ {k: {'count': len(v['values']), 'timestamps': v['timestamps']} for k, v in groups.items()} }"
        )

        grouped_result = await self.compute_group_components(groups, period, step, total_expected_count=16)
        if grouped_result is None:
            logging.warning("[WeatherUncertainty] Aborting Levening: could not compute grouped result.")
            return None, None, None
        
        logging.info(f"Levening group: {grouped_result}")

        levening = 10 * math.log10(sum(g["weighted_energy"] for g in grouped_result.values()))
        logging.info(f"[WeatherUncertainty][{period}] Computed levening from grouped energies: levening={round(levening, 2)}")

        levening_ref, uevening_ref, _, _ = self.compute_final_uncertainty_interval(grouped_result, levening, uncertainty)
        return levening, levening_ref, uevening_ref

    async def compute_lnight_temporal_uncertainty(self, uncertainty=0.6):
        source_acoustic_table = "LAeq30min"
        source_weather_table = "weather30min"
        step = timedelta(minutes=30)
        period = "night"

        start_interval = (self.start_time - timedelta(days=1)).replace(hour=23, minute=0, second=0)
        end_interval = self.start_time.replace(hour=7, minute=0, second=0)

        acoustic_map, weather_map, expected_timestamps = await self.fetch_interval_data(source_acoustic_table, source_weather_table, start_interval, end_interval, step)

        groups = group_values_by_weather_window(acoustic_map, weather_map, expected_timestamps, self.noise_source_position, period)
        if groups is None:
            logging.warning("[WeatherUncertainty] Aborting Lnight: missing acoustic/weather data or invalid window classification.")
            return None, None, None 
        
        logging.info(
            f"[WeatherUncertainty][{period}] Grouped values summary: "
            f"{ {k: {'count': len(v['values']), 'timestamps': v['timestamps']} for k, v in groups.items()} }"
        )

        grouped_result = await self.compute_group_components(groups, period, step, total_expected_count=16)
        if grouped_result is None:
            logging.warning("[WeatherUncertainty] Aborting Lnight: could not compute grouped result.")
            return None, None, None

        logging.info(f"Lnight group: {grouped_result}")

        lnight = 10 * math.log10(sum(g["weighted_energy"] for g in grouped_result.values()))
        logging.info(f"[WeatherUncertainty][{period}] Computed lnight from grouped energies: lnight={round(lnight, 2)}")

        lnight_ref, unight_ref, _, _ = self.compute_final_uncertainty_interval(grouped_result, lnight, uncertainty)
        return lnight, lnight_ref, unight_ref

    async def fetch_interval_data(self, source_acoustic_table, source_weather_table, start_interval, end_interval, step):
        acoustic_map = await fetch_acoustic_data(self.connection_pool, self.acoustic_db_name, source_acoustic_table, start_interval, end_interval)
        weather_map = await fetch_weather_data(self.connection_pool, self.weather_db_name, source_weather_table, start_interval, end_interval)
        expected_timestamps = build_expected_timestamps(start_interval, end_interval, step)
        return acoustic_map, weather_map, expected_timestamps


    async def compute_group_components(self, groups, period, step, total_expected_count):
        grouped_result = {}

        for group_name, group_data in groups.items():
            values = group_data["values"]
            timestamps = group_data["timestamps"]

            # Skip completely empty groups
            if not values:
                logging.info(f"[WeatherUncertainty] Skipping empty group {group_name}")
                continue

            count = len(values)
            pk = count / total_expected_count # prob/occurence over group index pk 

            uk, enav = self.compute_group_uncertainty(values, count)

            if enav is None:
                logging.warning(f"[WeatherUncertainty] Invalid enav in group {group_name}")
                continue

            # Fetch LAF (numpy array already)
            p_values = await self.fetch_laf_values_for_group_timestamps(timestamps, step)
            if p_values is None:
                logging.warning(f"[WeatherUncertainty] Missing LAF for group {group_name}")
                continue

            lres = self.compute_l90_from_group(p_values)
            if lres is None:
                logging.warning(f"[WeatherUncertainty] Invalid lres in group {group_name}")
                continue

            result = self.compute_expanded_uncertainty(enav, uk, count, lres, pk)

            if result is None:
                logging.warning(f"[WeatherUncertainty] Failed expanded uncertainty for {group_name}")
                continue

            lk, u_k_prime, ures, cl_prime, cl_res, ulk, weighted_energy = result

            grouped_result[group_name] = {
                "values": values,
                "timestamps": timestamps,
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
                "pk": pk,
            }

        if not grouped_result:
            logging.warning(f"[WeatherUncertainty] No valid groups for {period}")
            return None

        return grouped_result

    async def fetch_laf_values_for_group_timestamps(self, timestamps, step):
        arrays = []

        for ts in timestamps:
            end_ts = ts + step

            arr = await fetch_laf_data(self.connection_pool, "LAF", "LAF", ts, end_ts)

            if arr is None:
                logging.warning(f"[WeatherUncertainty] Missing LAF data for interval {ts} -> {end_ts}")
                return None

            arrays.append(arr)

        return np.concatenate(arrays)

    @staticmethod
    def compute_group_uncertainty(values, count):
        if count == 0:
            return 0.0, None

        if count == 1:
            enav = float(values[0])
            return 0.0, round(enav, 2)

        energies = [10 ** (0.1 * v) for v in values]
        e_bar = sum(energies) / count
        enav = 10 * math.log10(e_bar)

        enav_energy = 10 ** (0.1 * enav)
        squared_diffs = [(10 ** (0.1 * v) - enav_energy) ** 2 for v in values]

        sk = math.sqrt(sum(squared_diffs) / (count - 1))
        uk = 10 * math.log10(enav_energy + sk) - enav

        return round(uk, 2), round(enav, 2)

    def compute_final_uncertainty_interval(self, grouped_result, l_value, uncertainty):
        """
        Computes final uncertainty for a period (day/evening/night)
        """

        # Step 1: Total weighted energy
        total_energy = sum(g['weighted_energy'] for g in grouped_result.values())

        if total_energy <= 0:
            logging.warning("[WeatherUncertainty] Invalid total_energy <= 0 in final uncertainty interval.")
            return None, None, None, None

        # Step 2: Contribution fractions (normalized)
        for g in grouped_result.values():
            g['cl'] = g['weighted_energy'] / total_energy

        # Step 3: cp factors (use weighted energy consistently)
        log_factor = 10 * math.log10(2.7)

        for g in grouped_result.values():
            g['cp'] = log_factor * g['cl']   # cleaner and equivalent

        # Step 4: Uncertainty aggregation
        upi = 0.05

        u_weight = math.sqrt(
            sum((g['ulk'] ** 2) * (g['cl'] ** 2) for g in grouped_result.values()) +
            sum((g['cp'] ** 2) * (upi ** 2) for g in grouped_result.values())
        )

        # Step 5: Final result
        l_ref = l_value + uncertainty
        u_ref = math.sqrt(u_weight ** 2 + 0.2 ** 2)

        return l_ref, u_ref, u_weight, grouped_result

    @staticmethod
    def compute_expanded_uncertainty(enav, uk, count, lres, pk):
        """
        Computes expanded uncertainty for a group.
        """

        # If no data at all -> skip upstream (should not reach here)
        if enav is None:
            return None

        # If only 1 value -> no statistical uncertainty
        if count < 2:
            lk = enav
            u_k_prime = 0.0
            ures = 0.0
            cl_prime = 1.0
            cl_res = 0.0
            ulk = 0.0
            weighted_energy = 10 ** (0.1 * lk) * pk

            return lk, u_k_prime, ures, cl_prime, cl_res, ulk, weighted_energy

        # Normal case
        u_k_prime = uk / math.sqrt(count)
        ures = 4 / math.sqrt(count)

        # ISO safeguard
        if enav - lres < 3:
            lk = enav
            cl_prime = 1.0
            cl_res = 0.0
            ulk = u_k_prime

        else:
            linear_diff = 10 ** (0.1 * enav) - 10 ** (0.1 * lres)
            if linear_diff <= 0:
                return None

            lk = 10 * math.log10(linear_diff)

            denom = 1 - 10 ** (-0.1 * (enav - lres))
            if abs(denom) < 1e-6:
                return None

            cl_prime = 1 / denom
            cl_res = cl_prime * 10 ** (-0.1 * (enav - lres))

            inner = (cl_prime ** 2) * (u_k_prime ** 2) + (cl_res ** 2) * (ures ** 2)
            if inner < 0:
                return None

            ulk = math.sqrt(inner)

        weighted_energy = 10 ** (0.1 * lk) * pk

        return lk, u_k_prime, ures, cl_prime, cl_res, ulk, weighted_energy
        
    @staticmethod
    def compute_l90_from_group(values):
        if values is None or values.size == 0:
            return None

        p_values = np.percentile(values, 10)
        return round(float(p_values), 2)