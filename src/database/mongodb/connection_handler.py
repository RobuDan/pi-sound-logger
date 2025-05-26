import asyncio
from asyncio import Lock
import logging
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo.errors import ConnectionFailure
import aiohttp
import aiomysql
from contextlib import asynccontextmanager
import json 

from utils.env_config_loader import Config


class ConnectionHandler:
    def __init__(self, mongo_url, mysql_pool=None):
        self.mongo_url = mongo_url
        self.client = None
        self.mysql_pool = mysql_pool
        self.logs_mysql = None
        self.mongodb_connection_event = asyncio.Event()
        self.connection_lock = Lock()
        self.shut_down = False
        self.monitor_task = None
        self.is_monitoring_active = False 

    async def get_client(self):
        return self.client
    
    async def check_internet_connectivity(self):
        url = "http://www.google.com"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as response:
                    if response.status == 200 and self.logs_mysql is not None and not self.shut_down:
                        await self.logs_mysql.insert_log_to_mysql(
                            event_type='Internet Check',
                            status='Success',
                            message='Internet connectivity check successful.',
                            details={'http_status': response.status}
                        )
                    return response.status == 200
        except Exception as e:
            if self.logs_mysql is not None and not self.shut_down:
                await self.logs_mysql.insert_log_to_mysql(
                    event_type='Internet Check',
                    status='Exception',
                    message='Internet connectivity check failed.',
                    details={'exception': str(e)}
                )
            return False

    async def connect(self):
        attempt = 0
        while not self.shut_down:
            async with self.connection_lock:
                try:
                    if await self.check_internet_connectivity():
                        if self.client is None:
                            self.client = AsyncIOMotorClient(self.mongo_url, maxPoolSize=120)
                        
                        await asyncio.wait_for(self.client.admin.command('ping'), timeout=3)
                        self.mongodb_connection_event.set()
                        if self.logs_mysql is not None and not self.shut_down:
                            await self.logs_mysql.insert_log_to_mysql(
                                event_type='MongoDB Connection',
                                status='Connected',
                                message='Connected to MongoDB successfully with Motor.'
                            )
                        if not self.is_monitoring_active:
                            self.monitor_task = asyncio.create_task(self.monitor_connection())
                            self.is_monitoring_active = True
                        return self.client

                except TimeoutError:
                    if self.shut_down:
                        break

                except (ConnectionFailure, Exception) as e:
                    if self.logs_mysql is not None and not self.shut_down:
                        await self.logs_mysql.insert_log_to_mysql(
                            event_type='MongoDB Connection',
                            status='Failure',
                            message='Failed to connect or verify MongoDB.',
                            details={'attempt': attempt, 'error': str(e)}
                        )
                attempt += 1
                sleep_time = min(60, 2 ** attempt)
                await asyncio.sleep(sleep_time)
                if self.shut_down:
                    break

    async def monitor_connection(self):
        self.is_monitoring_active = True
        try:
            while not self.shut_down:
                try:
                    #before timeout=0.5
                    await asyncio.wait_for(self.client.admin.command('ping'), timeout=6)
                    await asyncio.sleep(6)
                    
                except (ConnectionFailure, asyncio.TimeoutError):
                    logging.warning("Lost connection to MongoDB. Attempting to reconnect...")
                    self.mongodb_connection_event.clear()
                    if self.client is not None:
                        self.client.close()
                        self.client = None
                    await self.connect()
        finally:
            if self.client is not None:
                self.client.close() 
                self.client = None
            self.is_monitoring_active = False

    async def set_mysql_pool(self, pool):
        self.mysql_pool = pool
        self.logs_mysql = LogsMySQL(self.mysql_pool)
        await self.logs_mysql.initialize()

    async def close(self):
        self.shut_down = True
        if self.client is not None:
            logging.info("Closing MongoDB connection...")
            self.client.close()
            if self.logs_mysql is not None:
                await self.logs_mysql.close_all_connections()
            logging.info("MongoDB connection closed.")

class LogsMySQL:
    def __init__(self, mysql_pool):
        self.pool = mysql_pool
        self.data_retention_days = Config.MYSQL_DATA_RETENTION
        self.db_name = "Logs"

    @asynccontextmanager
    async def get_connection(self, db_name=None):
        async with self.pool.acquire() as conn:
            if db_name:
                await conn.select_db(db_name)
            async with conn.cursor(aiomysql.DictCursor) as cur:
                yield conn, cur

    async def initialize(self):
        async with self.get_connection() as (conn, curr):
            await self.create_database(self.db_name)
    
    async def create_database(self, db_name):
        async with self.get_connection() as (conn, cur):
            await cur.execute(f"CREATE DATABASE IF NOT EXISTS `{db_name}`;")
            await conn.commit()
    
    async def insert_log_to_mysql(self, event_type, status, message, details=None):
        async with self.get_connection(self.db_name) as (conn, cur):
            await self._create_table_if_not_exists(cur, 'connectivity')
            insert_sql = """
            INSERT INTO connectivity (event_type, status, message, details, is_sent, is_aggregated)
            VALUES (%s, %s, %s, %s, %s, %s);
            """
            try:
                await cur.execute(insert_sql, (event_type, status, message, json.dumps(details) if details else None, 0, 1))
                await conn.commit()
            except Exception as e:  # Consider catching more specific exceptions
                logging.error(f"Error inserting {event_type} to MySQL: {e}")

    async def _create_table_if_not_exists(self, cur, table_name):
        create_table_sql = f"""
        CREATE TABLE IF NOT EXISTS `{table_name}` (
        id INT AUTO_INCREMENT PRIMARY KEY,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        event_type VARCHAR(255),
        status VARCHAR(100),
        message TEXT,
        details JSON,
        is_sent TINYINT(1) DEFAULT 0,
        is_aggregated TINYINT(1) DEFAULT 1,
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
        
    async def close_all_connections(self):
        self.pool.close()
        await self.pool.wait_closed()