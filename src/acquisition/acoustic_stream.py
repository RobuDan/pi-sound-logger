import asyncio
import logging
import datetime
import time
import math
import aiomysql
from contextlib import asynccontextmanager

from .help_functions.average import calculate_laeq
from utils.env_config_loader import Config

class AcousticStream:
    """
    Continuously acquires and logs acoustic parameters (e.g., LAeq, LAFmin, LAFmax) 
    from a microphone device in sync with real-time seconds.
    """

    def __init__(self, device, acoustic_parameters, mysql_pool, sample_interval, timestamp_provider=None):
        """
        Initializes the stream with device, target parameters, and timing settings.
        """
        self.device = device
        self.acoustic_parameters = acoustic_parameters
        self.mysql_pool = mysql_pool
        self.sample_interval = sample_interval
        self.samples_per_second = int(1 / self.sample_interval)
        self.timestamp_provider = timestamp_provider
        self.run_flag = False
        self.stream_task = None

        self.db_manager = DatabaseManagerAcoustic(self.mysql_pool, self.acoustic_parameters)

        if not self.timestamp_provider:
            raise ValueError("TimestampProvider is required for AcousticStream.")

    def wait_for_next_second(self) -> float:
        """
        Returns the sleep duration needed to align with the next full second.
        """
        return self.timestamp_provider.get_next_second_sleep_time()

    async def start(self):
        """
        Starts the stream task if not already running.
        """
        logging.info("AcousticStream starting...")
        if self.run_flag:
            logging.info("AcousticStream already running.")
            return
        
        # Initialize database
        await self.db_manager.initialize()

        if self.timestamp_provider:
            start_ts = self.timestamp_provider.get_start_timestamp()
            if start_ts:
                logging.info(f"Aligned start timestamp: {start_ts.isoformat(timespec='milliseconds')}")

        self.run_flag = True
        self.stream_task = asyncio.create_task(self._run_loop())

    async def _run_loop(self):
        """
        Main loop: aligns to wall time, samples data, logs results once per second.
        """
        try:
            await asyncio.sleep(self.wait_for_next_second())
            logging.info("Stream aligned to next second.")

            last_cycle_start = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0)

            while self.run_flag:
                base_time = last_cycle_start
                laf_values = []
                leq_values = []

                for i in range(self.samples_per_second):
                    try:
                        laf = self.device.read_level()
                        leq = self.device.read_leq()
                        laf_values.append(laf)
                        leq_values.append(leq)
                    except Exception as e:
                        logging.error(f"[Sample Error] {e}")
                        continue

                    # Sync sampling rate to real-time clock
                    target = base_time.timestamp() + ((i + 1) * self.sample_interval)
                    await asyncio.sleep(max(0, target - time.time()))

                if len(laf_values) < self.samples_per_second:
                    logging.warning(f"[{base_time}] Incomplete sample set. Skipping.")
                    continue

                try:
                    # Align to Bucharest time for both log and MySQL
                    timestamp_dt = base_time.astimezone(self.timestamp_provider.tz)
                    log_time = timestamp_dt.isoformat(timespec="milliseconds")
                    timestamp = timestamp_dt.strftime("%Y-%m-%d %H:%M:%S")  # For MySQL

                    log_parts = []

                    for param in self.acoustic_parameters:
                        if param == "LAeq":
                            value = calculate_laeq(leq_values)
                        elif param == "LAF":
                            value = laf_values[0]
                        elif param == "LAFmin":
                            value = min(laf_values)
                        elif param == "LAFmax":
                            value = max(laf_values)
                        else:
                            continue

                        # Validate value before logging or saving
                        if not isinstance(value, (int, float)) or math.isnan(value) or math.isinf(value):
                            logging.warning(f"[Validation Skip] {param} = {value}")
                            continue      

                        # Add to log
                        log_parts.append(f"{param}={value:.2f} dB") 

                        # Insert into MySQL
                        await self.db_manager.insert_data(param, timestamp, round(value, 2))

                        # logging.info(f"{timestamp}, {param}, {round(value, 2)}")
                        
                    # logging.info(f"[{log_time}] " + " | ".join(log_parts))

                except Exception as e:
                    logging.error(f"[Post-process Error] {e}")

                last_cycle_start = base_time + datetime.timedelta(seconds=1)

        except asyncio.CancelledError:
            logging.info("AcousticStream task cancelled.")
        except Exception as e:
            logging.error(f"Stream loop failure: {e}")

    async def cleanup(self):
        """
        Cancels the stream task if active.
        """
        logging.info("Cleaning up AcousticStream...")
        if self.stream_task:
            self.stream_task.cancel()
            await self.stream_task
        logging.info("Cleanup complete.")


class DatabaseManagerAcoustic:
    def __init__(self, connection_pool, sequence_names):
        self.pool = connection_pool
        self.sequence_names = sequence_names or []
        logging.info(sequence_names)
        self.data_retention_days = Config.MYSQL_DATA_RETENTION

    @asynccontextmanager
    async def get_connection(self, db_name=None):
        async with self.pool.acquire() as conn:
            if db_name:
                await conn.select_db(db_name)
            async with conn.cursor(aiomysql.DictCursor) as cur:
                yield conn, cur
    
    async def initialize(self):
        async with self.get_connection() as (conn, cur):
            for seq_name in self.sequence_names: 
                await self.create_database(seq_name)

    async def create_database(self, db_name):
        # Connect without selecting a database to execute CREATE DATABASE
        async with self.get_connection() as (conn, cur):
            await cur.execute(f"CREATE DATABASE IF NOT EXISTS `{db_name}`;")
            await conn.commit()
            logging.info(f"Database {db_name} created or already exists.")

    async def _create_table_if_not_exists(self, cur, table_name):
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
            WHERE TIMESTAMP < NOW() - INTERVAL {self.data_retention_days} DAY;
        """
        await cur.execute(create_event_sql)

    async def insert_data(self, db_name, timestamp, value):
        async with self.get_connection(db_name=db_name) as (conn, cur):
            await self._create_table_if_not_exists(cur, db_name)
            insert_sql = f"""
            INSERT INTO `{db_name}` (timestamp, value, is_sent, is_aggregated)
            VALUES (%s, %s, %s, %s);
            """
            await cur.execute(insert_sql, (timestamp, value, 0, 0))
            await conn.commit()