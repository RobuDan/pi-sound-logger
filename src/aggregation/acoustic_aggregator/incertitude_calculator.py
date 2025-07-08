"""
The follwoing computation are made by using the avaible formulas from
ISO 1996-2 Annex G.
"""

import math
import numpy as np
import asyncio
import logging
from datetime import timedelta
from collections import defaultdict

from .value_aggregator import ValueAggregator


class IncertitudeCalculator(ValueAggregator):
    def __init__(self, param, connection_pool, time_manager):
        super().__init__(param, connection_pool, time_manager)
        self.db_name = param
        self.subscribe_to_intervals(['1min', '24h'])  # Keep '1min' only for testing if needed
        logging.info("[Incertitude] Subscribed to intervals.")

    async def notifyAboutInterval(self, interval, start_time, end_time):
        """ Starts with safety wait of 25 seconds."""
        await asyncio.sleep(25) # Safety wait so all data is populated

        # Fetch precomputed values
        lday, levening, lnight = await self.fetch_lden_components(
            self.db_name, table_name="Lden", timestamp=start_time
        )

        if None in (lday, levening, lnight):
            logging.error("Missing Lden components. Aborting uncertainty computation.")
            return 
        
        # Compute uncertainty
        lday_ref, uday_ref = await self.compute_lday_temporal_uncertainty(self.db_name, start_time, end_time, lday)
        levening_ref, uevening_ref = await self.compute_levening_temporal_uncertainty(self.db_name, start_time, end_time, levening)
        lnight_ref, unight_ref = await self.compute_lnight_temporal_uncertainty(self.db_name, start_time, end_time, lnight)

        # Final U(Lden)
        u_lden = self.compute_lden_uncertainty(
            lday_ref, uday_ref,
            levening_ref, uevening_ref,
            lnight_ref, unight_ref
        )

        logging.info(f"[Incertitude] U(Lden) = ±{u_lden:.2f} dB")
        await self.insert_aggregated_value(self.db_name, "U_Lden", start_time, u_lden)
        
    async def compute_lday_temporal_uncertainty(self, db_name, start_time, end_time, lday):
        """
        Entry point for computing U(Lday), with group preparation and final uncertainty logic.
        """
        # Step 1: Compute grouped data with all per-group logic
        source_table_name = "LAeq1h" # Base data hourly
        # Define group intervals (each is 3 hours)
        # Build group datetime ranges
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

        grouped_result = await self.compute_groups_components(db_name, source_table_name, start_time, group_datetimes)

        if grouped_result is None or len(grouped_result) < 4:
            logging.warning("[U(Lday)] Not all 4 groups available. Aborting.")
            return

        # Step 2: Compute final U(Lday) using grouped data + lday
        lday_ref, uday_ref, _, _ = self.compute_final_uncertainty_interval(grouped_result, lday)

        # Save or log only what's needed:
        logging.info(f"[U(Lday)] Final: {lday_ref:.2f} ± {uday_ref:.2f} dB")

        return lday_ref, uday_ref

    async def compute_levening_temporal_uncertainty(self, db_name, start_time, end_time, levening):
        """
        Compute U(Levening) from 15-minute LAeq data grouped in 4 x 1-hour intervals.
        Each group consists of 4 15-minute values.
        """
        # Target database is 15 min
        source_table_name = "LAeq15min"

        # Evening split: 4 groups, each 1h wide using 15-min data
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

        grouped_result = await self.compute_groups_components(db_name, source_table_name, start_time, group_datetimes)

        if grouped_result is None or len(grouped_result) < 4:
            logging.warning("[U(Levening)] Not all 4 groups available. Aborting.")
            return None

        levening_ref, uevening_ref, _, _ = self.compute_final_uncertainty_interval(grouped_result, levening)
        logging.info(f"[U(Levening)] Final: {levening_ref:.2f} ± {uevening_ref:.2f} dB")

        return levening_ref, uevening_ref


    async def compute_lnight_temporal_uncertainty(self, db_name, start_time, end_time, lnight):
        """
        Entry point for computing U(Lnight), using 4x 2-hour groups with 30-minute LAeq values.
        First group spans across two calendar days (23:00–01:00).
        """
        source_table_name = "LAeq30min"  # Night uses 30-min interval data

        # Define group datetime ranges (4 groups, 2h each, 4 × 30min values/group)
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

        # Step 1: Compute grouped data with all per-group logic
        grouped_result = await self.compute_groups_components(db_name, source_table_name, start_time, group_datetimes)

        if grouped_result is None or len(grouped_result) < 4:
            logging.warning("[U(Lnight)] Not all 4 groups available. Aborting.")
            return None

        # Step 2: Compute final U(Lnight)
        lnight_ref, unight_ref, _, _ = self.compute_final_uncertainty_interval(grouped_result, lnight)

        # Log final result
        logging.info(f"[U(Lnight)] Final: {lnight_ref:.2f} ± {unight_ref:.2f} dB")

        return lnight_ref, unight_ref


    async def compute_groups_components(self, db_name, source_table_name, start_time, group_intervals):
        """
        Computes per-group uncertainty details for the Lday, Levening, Lnight uncertainty..
        """
        grouped_result = {}

        for group_name, (group_start, group_end) in group_intervals.items():
            # Fetch LAeq data (1h, 30min, or 15min depending on caller)

            # Fetch values for each group
            values = await self.fetch_records(db_name, source_table_name, group_start, group_end)
            # Fetch values from Laf database to compute Lres(L90)
            p_values = await self.fetch_records("LAF", "LAF", group_start, group_end)

            if not values:
                logging.warning(f"Aborting U(Lday): missing data in group {group_name} ({group_start} to {group_end})")
                return None # abort if the group is missing
            count = len(values)

            uk, enav = self.compute_group_uncertainty(values, count)
            lres = self.compute_l90_from_group(p_values)
            lk, u_k_prime, ures, cl_prime, cl_res, ulk, weighted_energy = self.compute_expanded_uncertainty(enav, uk, count, lres)
            
            grouped_result[group_name] = {
                'values': values,
                'count': count,
                'enav': enav,
                'lres': lres,
                'lk': lk,
                'u_k_prime': u_k_prime,
                'ures': ures,
                'cl_prime': cl_prime,
                'cl_res': cl_res,
                'ulk': ulk,
                'weighted_energy': weighted_energy,
            }

    def compute_final_uncertainty_interval(self, grouped_result, lday):
        """
        Uses per-group uncertainty results to compute U(Lday) and Lday_ref, respective for night and evening.
        """
         # Step 1: Total energy
        total_energy = sum(g['weighted_energy'] for g in grouped_result.values())

        # Step 2: Compute group weight fractions
        for g in grouped_result.values():
            g['cl'] = g['weighted_energy'] / total_energy

        # Step 2.5: Compute cp weights for each group based on lk_energy
        for g in grouped_result.values():
            g['lk_energy'] = 10 ** (0.1 * g['lk'])  # store for reuse

        log_factor = 10 * math.log10(2.7)

        for g in grouped_result.values():
            g['cp'] = log_factor * (g['lk_energy'] / total_energy)
        # Step 3: Compute weighted uncertainty
        upi = 0.05
        u_weight = math.sqrt(
            sum((g['ulk'] ** 2) * (g['cl'] ** 2) for g in grouped_result.values()) +
            sum((g['cp'] ** 2) * (upi ** 2) for g in grouped_result.values())
        )
        # Step 4: Final Lday ref + uncertainty
        l_ref = lday + 1.0
        u_ref = math.sqrt(u_weight ** 2 + 0.2 ** 2)

        return l_ref, u_ref, u_weight, grouped_result

    @staticmethod
    def compute_group_uncertainty(values, count):
        """
        Computes the uncertainity for a group of LAEQ values.

            Args:
            values (List[float]): List of LAeq values in dB
            count (int): Number of values 

        Returns:
            uk (float): Uncertainty for the group in dB
            enav (float): Energy-average level in dB (used for Lk or reporting)
        """
        if count < 2:
            return 0.0, None # Not enough data
        
        # Step 1: Convert dB to linear energy
        energies = [10 ** (0.1 * v) for v in values]

        # Step 2: Mean of energies
        e_bar = sum(energies)/ count

        # Step 3: Convert back to dB (nergy average level)
        enav = 1 * math.log10(e_bar)

        # Step 4: Compute squared deviations from enva (in linear domain)
        enav_energy = 10 ** (0.1 * enav)
        squared_diffs = [(10 ** (0.1 * v) - enav_energy) ** 2 for v in values]

        # Step 5: Standard deviation in energy domain
        sk = math.sqrt(sum(squared_diffs) / (count - 1))

        # Step 6: Convert to db uncertainty
        uk = 10 * math.log10(enav_energy + sk) - enav

        return uk, enav
            
    @staticmethod
    def compute_l90_from_group(values):
        """
        Computes L90 (the 90th percentile) from a list of LAF values.
        This approximates background noise level (Lres).

        Args:
            values (List[float]): List of dB values (e.g., LAF per second)

        Returns:
            float: L90 value in dB (used as Lres)
        """
        if not values:
            return None
        
        values = np.array(values, dtype=float)
            
        # Even though data integrity is checked before insertion, this is an extra measure
        values = values[np.isfinite(values)]
        if len(values) == 0:
            return None
        
        p_values = np.percentile(values, 90)

        return round(p_values, 2)
            
    @staticmethod
    def compute_expanded_uncertainty(enav, uk, count, lres):
        """
        Computes uLk — the expanded uncertainty of corrected Lk level,

        Args:
            enav (float): Mean energy level in dB (L'k)
            uk (float): Uncertainty for group in dB
            count (int): Number of samples in the group
            lres (float): Residual/background level (Percentile 90)
        
        Returns:
            tuple: (lk, u_k_prime, ures, cl_prime, cl_res, ulk)
        """
        if count < 2:
            return None
        
        # Step 1: L'k = enav
        # Step 2: u'k 
        u_k_prime = uk / math.sqrt(count)

        # Step 3: ures (fixed rule)
        ures = 4 / math.sqrt(count)

        # Step 4: Lk = corrected level after background substraction
        lk = 10 * math.log10(10 ** (0.1 * enav) - 10 ** (0.1 * lres)) 

        # Step 5: cL'
        cl_prime = 1 / (1 - 10 ** (-0.1 * (enav - lres))) 

        # Step 6: cLres
        cl_res = cl_prime * 10 ** (-0.1 * (enav - lres))

        # Step 7: uLk
        ulk = math.sqrt(
            (cl_prime ** 2) * (u_k_prime ** 2) +
            (cl_res ** 2) * (ures ** 2)
        )

        # Compute the weighted_energy
        weighted_energy = 10 ** (0.1 * lk) * 0.25
        return lk, u_k_prime, ures, cl_prime, cl_res, ulk, weighted_energy
        

    @staticmethod
    def compute_lden_uncertainty(lday_ref, uday_ref, levening_ref, uevening_ref, lnight_ref, unight_ref):
        """
        Computes combined expanded uncertainty U(Lden) based on uncertainties
        from Lday, Levening, and Lnight components using energy weighting.
        """
        # Convert L components to linear energy terms
        A = 12 * 10 ** (0.1 * lday_ref)
        B = 4 * 10 ** (0.1 * (levening_ref + 5))
        C = 8 * 10 ** (0.1 * (lnight_ref + 10))

        # Numerator: sum of squared energy-weighted uncertainties
        numerator = math.sqrt(
            (A ** 2) * (uday_ref ** 2) +
            (B ** 2) * (uevening_ref ** 2) +
            (C ** 2) * (unight_ref ** 2)
        )

        # Denominator: total energy sum
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
