import time 
import logging
import asyncio
import zlib 
import pickle
from pymongo import ASCENDING
import inspect
from pymongo.errors import BulkWriteError


from .audio_transfer import AudioTransfer 
from .microphone_details import MicrophoneDetails

class DataSyncManager:
    def __init__(self, mysql_pool, device, mongodb_connection_event, data_base, connection_handler, data_base_status, callback):
        self.mysql_pool = mysql_pool
        self.device = device
        self.connection_handler = connection_handler
        self.mongo_client = None
        self.data_base = data_base
        self.data_queue = None
        self.status_queue = None
        self.mongodb_connection_event = mongodb_connection_event
        self.mysql_fetcher = None
        self.mongo_transfer = None
        self.microphone_details = None
        self.data_base_status = data_base_status
        self.callback = callback
        self.tasks = []

    def set_mysql_pool(self, mysql_pool):
        self.mysql_pool = mysql_pool

    def set_device(self, device):
        self.device = device
        if self.microphone_details is not None:
            self.microphone_details.update_device(device)
            
    async def run(self):
        while True:
            try:
                # Ensure MongoDB is connected and MySQL pool is ready before starting tasks
                await self.mongodb_connection_event.wait()
                self.mongo_client = await self.connection_handler.get_client()

                if self.mysql_pool is None or self.mongo_client is None:
                    logging.error("Database resources not ready. Retrying...")
                    await asyncio.sleep(1)  # Retry after a delay
                    continue
                
                logging.info("MongoDB is connected and MySQL pool is ready. Starting or verifying tasks.")
                
                if not self.tasks:  # Start tasks if not already running
                    self.data_queue = asyncio.Queue()  # Properly reinitialize the queue
                    self.status_queue = asyncio.Queue() 
                    self.mysql_fetcher = MySQLDataFetcher(self.mysql_pool, self.data_queue, self.status_queue)  # Recreate the fetcher with the new queue
                    self.mongo_transfer = MongoDBDataTransfer(self.mongo_client, self.data_queue, self.data_base, self.status_queue)  # Recreate the transfer with the new queue
                    self.audio_transfer = AudioTransfer(self.mongo_client, self.mysql_pool, self.data_base, self.data_base_status,)
                    self.microphone_details = MicrophoneDetails(self.device, self.mongo_client, self.data_base_status, self.callback)
                    self.tasks = [
                        asyncio.create_task(self.mysql_fetcher.run()),
                        asyncio.create_task(self.mongo_transfer.run()),
                        asyncio.create_task(self.audio_transfer.run()),
                        asyncio.create_task(self.microphone_details.run())
                    ]
                    logging.info("Tasks started: MySQL fetching and MongoDB transferring.")

                # Continuously check if MongoDB connection is still active
                while self.mongodb_connection_event.is_set():
                    await asyncio.sleep(1)  # Check periodically

            except asyncio.CancelledError:
                logging.info("DataSyncManager.run() cancellation caught. Exiting.")
                break  # Exit the loop if the run method itself is cancelled

            finally:
                # If disconnected or cancelled, ensure all tasks are cancelled
                if self.tasks:
                    logging.info("MongoDB connection lost or shutdown requested. Stopping tasks.")
                    for task in self.tasks:
                        task.cancel()
                    await asyncio.gather(*self.tasks, return_exceptions=True)
                    await self.data_queue.put(None) 
                    await self.status_queue.put(None) 
                    self.tasks = []  # Clear the tasks list after they are cancelled

                self.mongo_client = None
                if not self.mongodb_connection_event.is_set():
                    await self.mongodb_connection_event.wait()

    async def stop(self):
            logging.info("Stopping DataSyncManager...")
            # Manually clear the event to help break out of any waits
            self.mongodb_connection_event.clear()
            for task in self.tasks:
                task.cancel()
            await asyncio.gather(*self.tasks, return_exceptions=True)
            if self.data_queue is not None and  self.status_queue is not None:
                try:
                    await self.data_queue.put(None)
                    await self.status_queue.put(None)
                except Exception as e:
                    logging.error(f"Failed to put sentinel in queue: {e}")
            logging.info("All tasks have been cancelled successfully.")

class MySQLDataFetcher:
    def __init__(self, mysql_pool, data_queue, status_queue):
        self.mysql_pool = mysql_pool
        self.data_queue = data_queue
        self.status_queue = status_queue
        self.db_table_map = {}
        self.schema_intern = {}
        self.reduced_schema = {}
        self.last_success = {}
        self.pending_ids = {}

    async def discover_databases_and_tables(self):
        """Discover databases and their tables and send tables with schema info to the queue."""
        try:
            async with self.mysql_pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute("SHOW DATABASES WHERE `Database` NOT IN ('information_schema', 'mysql', 'performance_schema', 'sys');")
                    databases = await cursor.fetchall()
                    for db in databases:
                        db_name = db[0]
                        await cursor.execute(f"SHOW TABLES FROM `{db_name}`;")
                        tables = await cursor.fetchall()
                        if db_name not in self.db_table_map:
                            self.db_table_map[db_name] = set()
                        for table in tables:
                            table_name = table[0]
                             #Ignore phpMyAdmin internal tables
                            if table_name.startswith("pma__"):
                                continue
                            self.db_table_map[db_name].add(table_name)
                            await cursor.execute(f"DESCRIBE `{db_name}`.`{table_name}`;")
                            columns = await cursor.fetchall()
                            schema_intern = [{"column_name": col[0], "data_type": col[1]} for col in columns if col[0] not in ['is_sent', 'is_aggregated']]
                            reduced_schema = [{"column_name": col[0], "data_type": col[1]} for col in columns if col[0] not in ['id', 'is_sent', 'is_aggregated']]
                            self.schema_intern[table_name] = schema_intern
                            self.reduced_schema[table_name] = reduced_schema
                            compressed_schema = zlib.compress(pickle.dumps(reduced_schema))
                            message = {
                                    "action": "prepare_collection",
                                    "data": {
                                        "table_name": table_name,
                                        "schema": compressed_schema
                                    }
                                }
                            #logging.info(f"{table_name}{schema}")
                            await self.data_queue.put(message)
                            self.last_success[table_name] = True
        except Exception as e:
            logging.error(f"Unexpected error: {e}")

    async def fetch_table_data(self, db_name, table):
        """Fetches data only if the last batch was successful."""
        if self.last_success.get(table, False):
            async with self.mysql_pool.acquire() as conn:
                await conn.select_db(db_name)
                async with conn.cursor() as cursor:
                    schema = self.schema_intern.get(table, [])
                    select_columns = ', '.join(f"`{col['column_name']}`" for col in schema)
                    query = f"SELECT {select_columns} FROM `{table}` WHERE `is_sent` = 0 LIMIT 3600;"
                    await cursor.execute(query)
                    results = await cursor.fetchall()
                    if results:
                        #ids = [row[schema.index({'column_name': 'id', 'data_type': 'some_type'})] for row in results]
                        id_index = next((i for i, col in enumerate(schema) if col['column_name'] == 'id'), None)
                        if id_index is None:
                            logging.error(f"'id' column not found in the schema {table}")
                            return
                        ids = [row[id_index] for row in results]
                        data_only = [tuple(col for idx, col in enumerate(row) if idx != id_index) for row in results]
                        compressed_data = zlib.compress(pickle.dumps(data_only))
                        message = {
                            "action": "insert",
                            "data": {
                                "table_name": table,
                                "info": compressed_data
                            }
                        } 
                        #logging.info(f"{results}")
                        self.pending_ids[table] = ids
                        #logging.info(f"{self.pending_ids}")
                        await self.data_queue.put(message)
                        self.last_success[table] = False
                        #logging.info(f"Fetched {len(results)} records from {db_name}.{table}")

    async def fetch_data(self):
        """Fetch data from each table of each database based on stored mappings."""
        tasks = []
        try:
            for db_name, tables in self.db_table_map.items():
                for table in tables:
                    task = self.fetch_table_data(db_name, table)
                    tasks.append(task)
            await asyncio.gather(*tasks)
        except Exception as e:
            logging.error(f"Unexpected error in fetch_data: {table}{e}")

    async def run(self):
        """Main execution loop. Starts by firstly discoveryng the database."""
        await self.discover_databases_and_tables()
        # Launch background tasks
        discovery_task = asyncio.create_task(self.recurring_discover(600))
        data_fetch_task = asyncio.create_task(self.continuous_data_fetch(1))

        try:
            await self.process_messages()
        except Exception as e:
            logging.error(f"Unexpected error in run method of MySQLDataFetcher: {e}")
        except asyncio.CancelledError:
            logging.info("MySQLDataFetcher task was cancelled")
        finally:
            discovery_task.cancel()
            data_fetch_task.cancel()
            await asyncio.gather(discovery_task, data_fetch_task, return_exceptions=True)
            await self.stop()
            
    async def recurring_discover(self, interval):
        """Periodically discover databases and tables."""
        while True:
            await self.discover_databases_and_tables()
            await asyncio.sleep(interval)  # Waits for the specified interval (default 10 minutes)

    async def continuous_data_fetch(self, interval):
        """Continuously fetch data at specified intervals."""
        while True:
            await self.fetch_data()
            await asyncio.sleep(interval)

    async def process_messages(self):
        """Continuously processing messages from the status_queue"""
        try:
            while True:
                message = await self.status_queue.get()
                if message is None:
                    break
                
                action = message['action']
                details = message['data']

                # Delegate the action to the corresponding handler
                if action == 'insert_success':
                    await self.handle_insert_success(details)
                else:
                    logging.warning(f"Unhandled action type: {action}")

        except Exception as e:
            logging.error(f"Unexpected error in process_messages: {e}")

    async def handle_insert_success(self, details):
        """Handle the case where messages type is insert_succes"""
        table_name = details['table_name']
        records_count = details['records_count']
        await self.mark_success(table_name)
        #logging.info(f"Success received for {table_name} with {records_count} records inserted.")

    async def mark_success(self, table_name):
        """Mark a table's last batch as successful upon receiving confirmation, and modify is_send from 0 to 1 for each batch"""
        db_name = next((db for db, tables in self.db_table_map.items() if table_name in tables), None)
        
        if not db_name:
            logging.error(f"No database found for table {table_name}")
            return

        ids = self.pending_ids.pop(table_name, [])
        if ids:
            async with self.mysql_pool.acquire() as conn:
                await conn.select_db(db_name)
                async with conn.cursor() as cursor:
                    placeholders = ', '.join(['%s'] * len(ids))
                    update_query = f"UPDATE `{table_name}` SET `is_sent` = 1 WHERE `id` IN ({placeholders});"
                    await cursor.execute(update_query, ids)
                    await conn.commit()
                self.last_success[table_name] = True
            #logging.info(f"Marked {ids} records as sent in {table_name}")
        else:
            logging.info(f"No records to update for {table_name}")

    async def stop(self):
        await self.data_queue.put(None)
        await self.status_queue.put(None)
    
class MongoDBDataTransfer:
    def __init__(self, mongo_client, data_queue, data_base, status_queue):
        self.mongo_client = mongo_client
        self.data_queue = data_queue
        self.data_base = data_base
        self.status_queue = status_queue
        self.schema_map = {}
        self.num_workers = 10 # Not right; TO BE REVISITED

    async def create_schema_map(self, table_name, schema):
        column_names = [col['column_name'] for col in schema]
        self.schema_map[table_name] = column_names
        #logging.info(f"Schema map updated for {table_name}: {self.schema_map[table_name]}")

    async def ensure_collection_exists(self, table_name, schema):
        self.db = self.mongo_client[self.data_base]
        collection_name = table_name.lower()
        existing_collections = await self.db.list_collection_names()

        # Determine granularity for time series collections based on the table name
        granularity = 'seconds'
        if '1min' in collection_name or '5min' in collection_name:
            granularity = 'minutes'
        elif '30min' in collection_name or '1h' in collection_name:
            granularity = 'hours'

        if collection_name not in existing_collections:
            if collection_name != "connectivity":
                # Create time series collections without a meaningful metaField, just for TTL compliance
                await self.db.create_collection(
                    collection_name,
                    timeseries={
                        'timeField': 'timestamp',
                        'metaField': 'metadata',  # Simple metaField for TTL compliance
                        'granularity': granularity
                    }
                )
                logging.info(f"Time series collection {collection_name} with granularity {granularity} created.")

                # Define a simple TTL index with a partialFilterExpression that minimally uses the metaField
                # This value needs to be placed iside .env file, still testing memory usage with different devices
                # TO BE REVISITED 
                self.ttl_seconds = 60 * 60 * 24 * 14  # 60 days in seconds 60 * 60 * 24 * 60 
                await self.db[collection_name].create_index(
                    [("timestamp", ASCENDING)],
                    expireAfterSeconds=self.ttl_seconds,
                    partialFilterExpression={"metadata": {"$exists": True}}
                )

                logging.info(f"TTL index on 'timestamp' created for {collection_name} with a 60-day expiration.")
            else:
                # Create regular collection for 'connectivity' and apply schema validation
                await self.db.create_collection(collection_name)
                # Indexing for the 'connectivity' collection
                await self.db[collection_name].create_index([("timestamp", ASCENDING)], expireAfterSeconds=self.ttl_seconds)
                logging.info(f"Index on 'timestamp' created for {collection_name}.")
        #else:
            #logging.info(f"Collection {collection_name} already exists.")

    async def send_success(self, table_name, records_count):
        message = {
            "action": "insert_success",
            "data": {
                "table_name": table_name,
                "records_count": records_count
            }
        }
        await self.status_queue.put(message)

    async def insert_data(self, table_name, compressed_data):
        start_time = time.perf_counter()
        try:
            decompress_start = time.perf_counter()
            batch_data = pickle.loads(zlib.decompress(compressed_data))
            decompress_end = time.perf_counter()
            
            if table_name not in self.schema_map:
                logging.error(f"No schema map found for table {table_name}. Data insertion aborted.")
                return

            column_names = self.schema_map[table_name]
            documents = []

            for data_tuple in batch_data:
                document = {column_names[i]: data_tuple[i] for i in range(min(len(column_names), len(data_tuple)))}
                documents.append(document)

            insert_start = time.perf_counter()
            collection = self.db[table_name.lower()]

            await collection.insert_many(documents)
            insert_end = time.perf_counter()
            end_time = time.perf_counter()
            # Call success function
            await self.send_success(table_name, len(documents))
            #logging.info(f"Successfully inserted {len(documents)} records into '{table_name}' in {end_time - start_time:.2f}s. "
            #            f"Decompression: {decompress_end - decompress_start:.2f}s, Insertion: {insert_end - insert_start:.2f}s.")

        except BulkWriteError as bwe:
            logging.error(f"Bulk write error: {bwe.details}")
        except (pickle.PickleError, zlib.error) as e:
            logging.error(f"Error decompressing or unpickling data for {table_name}: {e}")
        except Exception as e:
            logging.error(f"Error processing 'insert' for {table_name}: {e}")
        finally:
            if 'end_time' not in locals():
                end_time = time.perf_counter()
                logging.info(f"Task for '{table_name}' ended prematurely after {end_time - start_time:.2f}s.")

    async def process_data(self, message):
        """This function processes the messages received from the queue, decompresses and unpickles before passing to where it is needed"""
        action = message['action']
        details = message['data']
        
        if action == 'prepare_collection':
            try:
                table_name = details['table_name']
                compressed_schema = details['schema']
                schema = pickle.loads(zlib.decompress(compressed_schema))
                await self.ensure_collection_exists(table_name, schema)
                await self.create_schema_map(table_name, schema)
            except (pickle.PickleError, zlib.error) as e:
                logging.error(f"Error decompressing or unpickling schema for {table_name}: {e}")
            except Exception as e:
                logging.error(f"Error processing 'prepare_collection' for {table_name}: {e}")

        elif action == 'insert':
            try:
                table_name = details['table_name']
                compressed_data = details['info']
                await self.insert_data(table_name, compressed_data)
            except Exception as e:
                logging.error(f"Error initializing 'insert' for {table_name}: {e}")
                raise

    async def run(self):
        tasks = []
        try:
            while True:
                data = await self.data_queue.get()
                if data is None:  # Check for a sentinel value to end the loop
                    break
                task = asyncio.create_task(self.process_data(data))
                tasks.append(task)
                # Optionally limit the number of concurrent tasks
                if len(tasks) >= self.num_workers:
                    done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                    tasks = list(pending)
        except Exception as e:
            logging.error(f"Unexpected error in run method of MongoDBDataTransfer: {e}")
        except asyncio.CancelledError:
            logging.info("MongoDBDataTransfer task was cancelled")
        finally:
            await asyncio.gather(*tasks)
            await self.stop()

    async def stop(self):
        """Cleanly shut down the data transfer, ensuring all resources are properly released."""
        try:
            await self.data_queue.put(None)  # Signal the run loop to terminate
            await self.status_queue.put(None)
        except Exception as e:
            logging.error(f"Error sending termination signal to the queue: {e}")

        # Attempt to close the MongoDB client connection
        if self.mongo_client is not None:
            try:
                self.mongo_client.close()
                logging.info("MongoDB client connection successfully closed.")
            except Exception as e:
                logging.error(f"Error closing MongoDB client connection: {e}")