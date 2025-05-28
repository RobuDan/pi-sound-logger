import os
import logging
import asyncio
import numpy as np
from datetime import datetime, timedelta
from .value_aggregator import ValueAggregator
from utils.env_config_loader import Config

#logging.info(f"LAeqAggregator notified for 1min interval: Start Time - {start_time}, End Time - {end_time}")

class LAeqAggregator(ValueAggregator):
    def __init__(self, param, connection_pool, time_manager):
        super().__init__(param, connection_pool, time_manager)
        self.db_name = param
        self.data_retention_days = Config.MYSQL_DATA_RETENTION
        self.subscribe_to_intervals(['1min', '5min', '15min', '30min', '1h', '24h'])
    
    async def notifyAboutInterval(self, interval, start_time, end_time):
        if interval == '24h':
            await self.aggregate_data(self.db_name, '24h', 'LAeq1h', 'LAeq24h', start_time, end_time)
            await self.aggregate_lden(self.db_name, start_time, end_time)
        else:
            source_table_name = "LAeq" if interval == '1min' else "LAeq1min"
            target_table_name = f"LAeq{interval}" if interval != '1min' else "LAeq1min"
            await self.aggregate_data(self.db_name, interval, source_table_name, target_table_name, start_time, end_time)
    
    async def aggregate_data(self, db_name, interval, source_table_name, target_table_name, start_time, end_time):
        sound_levels = await self.fetch_records(db_name, source_table_name, start_time, end_time)
        laeq_value = self.calculate_laeq(sound_levels)
        if laeq_value is not None:
            laeq_value = round(laeq_value, 2)
            # Only mark as aggregated if using raw data (1min interval) LOGICA TREBUIE MODIFICATA, 
            #DATELE TREBUIES MARKATE CU IS_AGGREGATED PE BAZA DE INTERVAL, MAI SIMPLU 
            #if mark_as_aggregated:
                #await self.mark_as_aggregated(source_db_path, source_table_name, start_time, end_time)
            # Insert aggregated value into the appropriate database
            await self.insert_aggregated_value(db_name, target_table_name, start_time, laeq_value)
        else:
            logging.info(f"No LAeq value calculated for interval {start_time} to {end_time}")

    async def aggregate(self):
        #Empty function
        pass
    
    async def aggregate_lden(self, db_name, start_time, end_time): 
        logging.info(f"LDEN aggregator gets called")
        await asyncio.sleep(20)  
        logging.info(f"LDEN aggregator awatited 20s")
        lday_ro, timestamp_lday_ro, lday_eu = await self.aggregate_lday(db_name, start_time)
        levening_ro, timestamp_levening_ro, levening_eu = await self.aggregate_levening(db_name, start_time)
        lnight_ro, timestamp_lnight_ro, lnight_eu = await self.aggregate_lnight(db_name, start_time)

        lden_ro = self.calculate_lden(lday_ro, levening_ro, lnight_ro)
        lden_eu = self.calculate_lden(lday_eu, levening_eu, lnight_eu)

        # Log the results
        if lden_ro is not None and lden_eu is not None:
            logging.info(f"Computed L_DEN_RO: {lden_ro}")
            logging.info(f"Computed L_DEN_EU: {lden_eu}")
            # Insert the computed values into the database
            await self.insert_lden_values(db_name, "Lden", start_time, lden_ro, lden_eu, 
                                          lday_ro, timestamp_lday_ro, lday_eu, 
                                          levening_ro, timestamp_levening_ro, levening_eu, 
                                          lnight_ro, timestamp_lnight_ro, lnight_eu)
        else:
            logging.error("Failed to compute one or both L_DEN values.")
    
    async def insert_lden_values(self, db_name, table_name, timestamp, lden_ro, lden_eu, lday_ro, timestamp_lday_ro, lday_eu, levening_ro, timestamp_levening_ro, levening_eu, lnight_ro, timestamp_lnight_ro, lnight_eu):
        await self._create_lden_table_if_not_exists(db_name, table_name)
        async with self.connection_pool.acquire() as conn:
            await conn.select_db(db_name)
            async with conn.cursor() as cur:
                insert_sql = f"""
                INSERT INTO `{table_name}` (timestamp, lden_ro, lden_eu, lday_ro, timestamp_lday_ro, lday_eu, levening_ro, timestamp_levening_ro, levening_eu, lnight_ro, timestamp_lnight_ro, lnight_eu, is_sent, is_aggregated)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s);
                """
                await cur.execute(insert_sql, (timestamp, lden_ro, lden_eu, lday_ro, timestamp_lday_ro, lday_eu, levening_ro, timestamp_levening_ro, levening_eu, lnight_ro, timestamp_lnight_ro, lnight_eu, 0, 0))
                await conn.commit()

    async def _create_lden_table_if_not_exists(self, db_name, table_name):
        async with self.connection_pool.acquire() as conn:
            await conn.select_db(db_name)
            async with conn.cursor() as cur:
                create_table_sql = f"""
                CREATE TABLE IF NOT EXISTS `{table_name}` (
                    id INT PRIMARY KEY AUTO_INCREMENT,
                    timestamp TIMESTAMP NOT NULL,
                    lden_ro FLOAT,
                    lden_eu FLOAT,
                    lday_ro FLOAT,
                    timestamp_lday_ro TIMESTAMP,
                    lday_eu FLOAT,
                    levening_ro FLOAT,
                    timestamp_levening_ro TIMESTAMP,
                    levening_eu FLOAT,
                    lnight_ro FLOAT,
                    timestamp_lnight_ro TIMESTAMP,
                    lnight_eu FLOAT,
                    is_sent TINYINT NOT NULL DEFAULT 0,
                    is_aggregated TINYINT NOT NULL DEFAULT 0,
                    INDEX idx_timestamp (timestamp),
                    INDEX idx_is_sent (is_sent),
                    INDEX idx_is_aggregated (is_aggregated),
                    INDEX idx_is_sent_is_aggregated (is_sent, is_aggregated)
                );
                """
                await cur.execute(create_table_sql)

                # Add event for deleting old records every 1 day, entries older config days
                create_event_sql = f"""
                CREATE EVENT IF NOT EXISTS `ev_delete_old_data_{table_name}`
                ON SCHEDULE EVERY 1 DAY
                DO
                    DELETE FROM `{table_name}`
                    WHERE TIMESTAMP < NOW() - INTERVAL {self.data_retention_days} DAY;
                """
                await cur.execute(create_event_sql)
                await conn.commit()

    async def aggregate_lday(self, db_name, start_time):
        # Define the 6-hour overlapping intervals for L_day_ro
        intervals = [(start_time.replace(hour=7, minute=0) + timedelta(minutes=30*i),
                      start_time.replace(hour=7, minute=0) + timedelta(minutes=30*i) + timedelta(hours=6))
                     for i in range(13)]  # 13 intervals from 07:00 to 19:00

        max_laeq = float('-inf')
        timestamp_lday_ro = None  # Timestamp of the interval with the highest LAeq
        source_table_name = "LAeq1h"  # Base data is now hourly

        # Fetch and calculate LAeq for each 6-hour interval
        for start, end in intervals:
            sound_levels = await self.fetch_records(db_name, source_table_name, start, end)
            if sound_levels:
                laeq_value = self.calculate_laeq(sound_levels)
                if laeq_value is not None and laeq_value > max_laeq:
                    max_laeq = laeq_value
                    timestamp_lday_ro = start  # Store the start time of the interval with the highest LAeq

        # Calculate L_day_eu for the entire time interval from 7:00 AM to 7:00 PM
        lday_start_time = start_time.replace(hour=7, minute=0, second=0)
        lday_end_time = start_time.replace(hour=19, minute=0, second=0)
        full_day_sound_levels = await self.fetch_records(db_name, source_table_name, lday_start_time, lday_end_time)
        lday_eu = self.calculate_laeq(full_day_sound_levels) if full_day_sound_levels else None

        # Log the results
        if max_laeq != float('-inf'):
            logging.info(f"Maximum LAeq for L_day_ro: {max_laeq} at {timestamp_lday_ro}")
        else:
            logging.error("No valid LAeq values calculated for any 6-hour interval.")

        if lday_eu is not None:
            logging.info(f"Computed LAeq for L_day_eu: {lday_eu}")
        else:
            logging.error("No valid LAeq value calculated for the entire day.")

        return max_laeq, timestamp_lday_ro, lday_eu

    async def aggregate_levening(self, db_name, start_time):
        source_table_name = "LAeq15min"  # Data from 15-min intervals for the evening
        # Define evening time range in 24-hour format
        evening_start_time = start_time.replace(hour=19, minute=0, second=0)
        evening_end_time = start_time.replace(hour=22, minute=45, second=0)

        # Fetch all sound levels for the entire evening period
        sound_levels_with_timestamps = await self.fetch_records_with_timestamps(db_name, source_table_name, evening_start_time, evening_end_time)

        levening_ro = float('-inf')
        timestamp_levening_ro = None  # Timestamp of the interval with the highest LAeq

        # Calculate levening_ro from the highest LAeq value and track its timestamp
        for level, timestamp in sound_levels_with_timestamps:
            if level > levening_ro:
                levening_ro = level
                timestamp_levening_ro = timestamp

        # Calculate LAeq for the entire evening period for levening_eu
        levening_eu = self.calculate_laeq([level for level, _ in sound_levels_with_timestamps]) if sound_levels_with_timestamps else None

        # Log the results
        if levening_ro != float('-inf'):
            logging.info(f"Highest LAeq for levening_ro: {levening_ro} at {timestamp_levening_ro}")
        else:
            logging.error("No valid LAeq values calculated for the evening period.")

        return levening_ro, timestamp_levening_ro, levening_eu
    
    async def aggregate_lnight(self, db_name, start_time):
        source_table_name = "LAeq30min"  # Data from 30-min intervals for the night
        # Define night time range in 24-hour format
        night_start_time = start_time.replace(hour=23, minute=0, second=0) - timedelta(days=1)
        night_end_time = start_time.replace(hour=6, minute=30, second=0)

        # Fetch all sound levels and their timestamps for the night period
        sound_levels_with_timestamps = await self.fetch_records_with_timestamps(db_name, source_table_name, night_start_time, night_end_time)

        lnight_ro = float('-inf')
        timestamp_lnight_ro = None  # Timestamp of the interval with the highest LAeq

        # Calculate lnight_ro from the highest LAeq value and track its timestamp
        for level, timestamp in sound_levels_with_timestamps:
            if level > lnight_ro:
                lnight_ro = level
                timestamp_lnight_ro = timestamp

        # Calculate LAeq for the entire night period for lnight_eu
        lnight_eu = self.calculate_laeq([level for level, _ in sound_levels_with_timestamps]) if sound_levels_with_timestamps else None

        # Log the results
        if lnight_ro != float('-inf'):
            logging.info(f"Highest LAeq for lnight_ro: {lnight_ro} at {timestamp_lnight_ro}")
        else:
            logging.error("No valid LAeq values calculated for the night period.")

        return lnight_ro, timestamp_lnight_ro, lnight_eu

    async def fetch_records_with_timestamps(self, db_name, table_name, start_time, end_time):
        records = []
        async with self.connection_pool.acquire() as conn:
            await conn.select_db(db_name)  # Select the specific database
            async with conn.cursor() as cur:
                fetch_sql = f"""
                SELECT value, timestamp FROM `{table_name}` WHERE timestamp >= %s AND timestamp <= %s ORDER BY timestamp ASC;
                """
                await cur.execute(fetch_sql, (start_time, end_time))
                rows = await cur.fetchall()
                records = [(row[0], row[1]) for row in rows]  # Extracting both values and timestamps
        return records

    @staticmethod
    def calculate_lden(lday, levening, lnight):
        # Calculate L_DEN using the formula:
        # L_DEN = 10 * log10((12/24 * 10^(L_day/10) + 4/24 * 10^((L_evening + 5)/10) + 8/24 * 10^((L_night + 10)/10)))
        if lday is not None and levening is not None and lnight is not None:
            lden_value = 10 * np.log10(
                (12/24 * 10 ** (lday / 10)) +
                (4/24 * 10 ** ((levening + 5) / 10)) +
                (8/24 * 10 ** ((lnight + 10) / 10))
            )
            return round(lden_value, 2)
        else:
            return None
        
    @staticmethod
    def calculate_laeq(sound_levels):
        """
        Calculate the equivalent continuous sound level (LAeq) from a list of sound levels.
        
        Parameters:
        sound_levels (list of float): Sound levels in decibels (dB).
        
        Returns:
        float: LAeq value in decibels (dB), or None if sound_levels is empty.
        """
        sound_levels = np.array(sound_levels)
        T = len(sound_levels)  # Number of measurements
        
        if T > 0:
            # Calculate LAeq using the formula: 10 * log10(1/T * sum(10^(sound_levels/10)))
            laeq = 10 * np.log10(np.sum(10 ** (sound_levels / 10)) / T)
            return round(laeq, 2)
        else:
            return None