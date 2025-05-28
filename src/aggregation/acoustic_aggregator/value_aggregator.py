import logging
import aiomysql
from aggregation.base_aggregator import BaseAggregator

from utils.env_config_loader import Config

data_retention_days = Config.MYSQL_DATA_RETENTION

class ValueAggregator(BaseAggregator):
    async def insert_aggregated_value(self, db_name, table_name, start_time, laeq_value):
        await self._create_table_if_not_exists(db_name, table_name)
        async with self.connection_pool.acquire() as conn:
            await conn.select_db(db_name)
            async with conn.cursor() as cur:
                insert_sql = f"""
                INSERT INTO `{table_name}` (timestamp, value, is_sent, is_aggregated) VALUES (%s, %s, %s, %s);
                """
                await cur.execute(insert_sql, (start_time, laeq_value, 0, 0))
                await conn.commit()

    async def fetch_records(self, db_name, table_name, start_time, end_time):
            records = []
            async with self.connection_pool.acquire() as conn:
                await conn.select_db(db_name)  # Select the specific database
                async with conn.cursor() as cur:
                    fetch_sql = f"""
                    SELECT value FROM `{table_name}` WHERE timestamp >= %s AND timestamp <= %s;
                    """
                    await cur.execute(fetch_sql, (start_time, end_time))
                    rows = await cur.fetchall()
                    records = [row[0] for row in rows]
            return records
    
    #async def mark_as_aggregated(self, db_path, table_name, start_time, end_time):
       # async with aiosqlite.connect(db_path) as db:
           # await db.execute(
               # f"UPDATE {table_name} SET is_aggregated = 1 WHERE timestamp >= ? AND timestamp <= ?", 
               # (start_time, end_time)
           # )
           # await db.commit()


    async def _create_table_if_not_exists(self, db_name, table_name):
        async with self.connection_pool.acquire() as conn:
            await conn.select_db(db_name)
            async with conn.cursor() as cur:
                # Create the table if it does not exist
                create_table_sql = f"""
                CREATE TABLE IF NOT EXISTS `{table_name}` (
                    id INT PRIMARY KEY AUTO_INCREMENT,
                    timestamp TIMESTAMP NOT NULL,
                    value FLOAT NOT NULL,
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
                    WHERE timestamp < NOW() - INTERVAL {data_retention_days} DAY;
                """
                await cur.execute(create_event_sql)
                await conn.commit()
                