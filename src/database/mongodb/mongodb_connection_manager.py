import logging

from utils.env_config_loader import Config
from .connection_handler import ConnectionHandler
from .data_sync_manager import DataSyncManager 

class MongoDBConnectionManager:
    def __init__(self, callback=None):
        self.mongo_url = Config.MONGO_URL
        self.data_base = Config.SERIAL_NUMBER
        self.data_base_status = Config.DEVICE_STATUS_DB
        self.connection_handler = ConnectionHandler(self.mongo_url)
        self.mysql_pool = None
        self.device = None
        self.callback = callback
        self.data_sync_manager = DataSyncManager(self.mysql_pool, self.device, self.connection_handler.mongodb_connection_event, self.data_base, self.connection_handler, self.data_base_status, self.callback )

    async def set_mysql_pool(self, pool):
        self.mysql_pool = pool
        await self.connection_handler.set_mysql_pool(pool)
        self.data_sync_manager.set_mysql_pool(pool)
        logging.info("MySQL pool set in MongoDB manager.")

    async def set_device(self, device):
        self.device = device
        self.data_sync_manager.set_device(device)
        logging.info(f"Serial path set in MongoDB manager.")

    async def start(self):
        logging.info("Starting MongoDB Connection Manager using Motor...")
        await self.connection_handler.connect()
        #asyncio.create_task(self.data_sync_manager.run())
        await self.data_sync_manager.run()
        
    async def stop(self):
        logging.info("Stopping MongoDB Connection Manager...")
        try:
            await self.connection_handler.close()
        except Exception as e:
            logging.error(f"Error stopping connection handler: {e}")
        await self.data_sync_manager.stop()
