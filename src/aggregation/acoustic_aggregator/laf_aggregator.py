import logging
import numpy as np
from .value_aggregator import ValueAggregator

from utils.env_config_loader import Config

class LAFAggregator(ValueAggregator):
    def __init__(self, param, connection_pool, time_manager):
        super().__init__(param, connection_pool, time_manager)
        self.db_name = param
        self.data_retention_days = Config.MYSQL_DATA_RETENTION
        # Only compute percentiles for 1min and 24h
        self.subscribe_to_intervals(['1min', '24h'])

    async def notifyAboutInterval(self, interval, start_time, end_time):
        source_table_name = "LAF" # Fetch the data form the second table
        target_table_name = f"LAF_percentiles_{interval}" # Inser the data into a specific time interval table
        # source_table_name = "LAF" if interval == '1min' else "LAF_percentiles_1min"
        
        await self.aggregate_percentiles(self.db_name, interval, source_table_name, target_table_name, start_time, end_time)
    
    async def aggregate_percentiles(self, db_name, interval, source_table_name, target_table_name, start_time, end_time):
        values = await self.fetch_records(db_name, source_table_name, start_time, end_time)
        result = self.calculate_percentiles(values)

        if result:
            await self.insert_percentiles(db_name, target_table_name, start_time, result)
        else:
            logging.info(f"No valid LAF data to compute percentiles for {start_time} to {end_time}.")

    async def aggregate(self):
        # Expected by grandparent. Will use for regular LAF computation
        pass

    async def insert_percentiles(self, db_name, table_name, timestamp, percentiles: dict):
        await self._create_percentile_table_if_not_exists(db_name, table_name)
        async with self.connection_pool.acquire() as conn:
            await conn.select_db(db_name)
            async with conn.cursor() as cur:
                insert_sql = f"""
                INSERT INTO `{table_name}` (timestamp, L5, L10, L50, L90, L95, is_sent, is_aggregated)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s);
                """
                await cur.execute(insert_sql, (
                    timestamp,
                    percentiles.get("L5"),
                    percentiles.get("L10"),
                    percentiles.get("L50"),
                    percentiles.get("L90"),
                    percentiles.get("L95"),
                    0, 0
                ))
                await conn.commit()

    async def _create_percentile_table_if_not_exists(self, db_name, table_name):
        async with self.connection_pool.acquire() as conn:
            await conn.select_db(db_name)
            async with conn.cursor() as cur:
                create_table_sql = f"""
                CREATE TABLE IF NOT EXISTS `{table_name}` (
                    id INT PRIMARY KEY AUTO_INCREMENT,
                    timestamp TIMESTAMP NOT NULL,
                    L5 FLOAT NOT NULL,
                    L10 FLOAT NOT NULL,
                    L50 FLOAT NOT NULL,
                    L90 FLOAT NOT NULL,
                    L95 FLOAT NOT NULL,
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

    async def fetch_percentile_records(self, db_name, table_name, start_time, end_time):
        """Fetch all percentile values from LAF_percentiles_1min for the given interval."""
        records = []
        async with self.connection_pool.acquire() as conn:
            await conn.select_db(db_name)
            async with conn.cursor() as cur:
                fetch_sql = f"""
                SELECT L5, L10, L50, L90, L95
                FROM `{table_name}`
                WHERE timestamp >= %s AND timestamp <= %s;
                """
                await cur.execute(fetch_sql, (start_time, end_time))
                rows = await cur.fetchall()
                for row in rows:
                    # row = (L5, L10, L50, L90, L95)
                    records.append({
                        "L5": row[0],
                        "L10": row[1],
                        "L50": row[2],
                        "L90": row[3],
                        "L95": row[4]
                    })
        return records

    @staticmethod
    def calculate_percentiles(values):
        if not values:
            return None
        values = np.array(values, dtype=float)
        
        # Even though data integrity is checked before insertion, this is an extra measure
        values = values[np.isfinite(values)]
        if len(values) == 0:
            return None

        percentile_values = np.percentile(values, [95, 90, 50, 10, 5])
        
        return {
            "L5": round(percentile_values[0], 2),
            "L10": round(percentile_values[1], 2),
            "L50": round(percentile_values[2], 2),
            "L90": round(percentile_values[3], 2),
            "L95": round(percentile_values[4], 2)
        }
        
    @staticmethod
    def calculate_mean_percentiles(records):
        if not records:
            return None

        # Convert list of dicts to dict of lists
        percentile_data = {
            "L5": [],
            "L10": [],
            "L50": [],
            "L90": [],
            "L95": []
        }
        for row in records:
            for key in percentile_data:
                if key in row and isinstance(row[key], (int, float)):
                    percentile_data[key].append(row[key])

        result = {}
        for key, values in percentile_data.items():
            if values:
                result[key] = round(np.mean(values), 2)

        return result if result else None
