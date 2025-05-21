import asyncio
import aiomysql
import logging
from utils.env_config_loader import Config

class MySQLConnectionManager:
    """
    Manages the MySQL connection pool and handles retries on startup failure.
    """
    def __init__(self):
        self.host = Config.MYSQL_HOST
        self.port = int(Config.MYSQL_PORT)
        self.user = Config.MYSQL_USER
        self.password = Config.MYSQL_PASSWORD
        self.pool = None

    async def manager_start(self):
        """
        Attempts to create a connection pool with retries and exponential backoff.
        Returns the pool once successful.
        """
        attempt = 0 
        delay = 1 # Start with a 1-second delay

        while True: # Infinite loop to keep trying indefinitely
            try:
                logging.info(f"Connecting to MySQL (attempt {attempt + 1})...")
                self.pool = await aiomysql.create_pool(
                    host=self.host,
                    port=self.port,
                    user=self.user,
                    password=self.password,
                    minsize=1,
                    maxsize=100,
                    loop=asyncio.get_running_loop()
                )
                logging.info("MySQL connection pool established.")
                return self.pool
            except Exception as e:
                logging.error(f"MySQL connection attempt {attempt + 1} failed: {e}")
                attempt += 1
                await asyncio.sleep(delay)
                delay = min(delay * 2, 60)

            logging.error("All attempts to connect to MySQL failed.")
            # raise ConnectionError("Unable to establish a connection to MySQL after multiple retries.")
        
    async def manager_stop(self):
        """
        Closes the MySQL connection pool cleanly.
        """
        if self.pool:
            self.pool.close()
            await self.pool.wait_closed()
            logging.info("MySQL connection pool closed.")
