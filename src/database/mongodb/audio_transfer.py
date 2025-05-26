import os
import logging
import asyncio
from datetime import datetime
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import ASCENDING

from utils.env_config_loader import Config


class AudioTransfer:
    def __init__(self, mongo_client, mysql_pool, data_base, data_base_status,):
        self.mongo_client = mongo_client
        self.mysql_pool = mysql_pool
        self.data_base = data_base
        self.device_id = data_base
        self.collection_name = 'audio'
        self.data_base_status = data_base_status
        self.client_db_status = self.mongo_client[self.data_base_status]
        self.document_status =  self.client_db_status['microphones']
        #60 * 60 * 24 * 30  # 30 days in seconds
        self.ttl_seconds = 60 * 60 * 24 *30   # 10 *60 min hdays in seconds
        self.db = self.mongo_client[self.data_base]
        self.working_dir = self._setup_working_dir()
        self.initial_file_count = self.scan_directory()
        self.audio_trigger = None

    def _setup_working_dir(self):
        """Setup the working directory from where files are going to be collected."""
        dir_of_current_script = os.path.dirname(os.path.abspath(__file__))
        base_path = os.path.abspath(os.path.join(dir_of_current_script, '..', '..'))
        working_dir = os.path.join(base_path, 'data_storage', 'audio')
        return working_dir

    def scan_directory(self):
        """Identify how many audio files are in the working directory"""
        return len([name for name in os.listdir(self.working_dir) if name.endswith('.mp3')])
    
    async def initialize_audio_trigger(self):
        """Fetch and set the audio_trigger value from the database."""
        try:
            document = await self.document_status.find_one({'_id': self.device_id})
            if document and 'audio_trigger' in document:
                self.audio_trigger = document['audio_trigger']
                #logging.info(f"Audio trigger value set to: {self.audio_trigger}")
            else:
                logging.warning("No audio_trigger field found in the document.")
        except Exception as e:
            logging.error(f"Error fetching audio_trigger from the database: {e}")

    async def ensure_collection_exists(self):
        """Assure that there is a mongoDb collection, where the audio files are going to be inserted."""
        try:
            existing_collections = await self.db.list_collection_names()
            if self.collection_name not in existing_collections:
                await self.db.create_collection(self.collection_name)
                await self.db[self.collection_name].create_index([("timestamp", ASCENDING)], expireAfterSeconds=self.ttl_seconds)
                logging.info(f"Created TTL index on 'timestamp' with expiry of {self.ttl_seconds} seconds.")
        except Exception as e:
            logging.error(f"Error ensuring collection exists: {e}")

    async def fetch_record(self, db_name, table_name, time):
        try:
            async with self.mysql_pool.acquire() as conn:
                await conn.select_db(db_name)
                async with conn.cursor() as cur:
                    fetch_value = f"""
                    SELECT value FROM `{table_name}` WHERE timestamp = %s;
                    """
                    await cur.execute(fetch_value, (time,))
                    result = await cur.fetchone()
                    if result:
                        value = result[0]
                        #logging.info(f"Fetched value {value} for timestamp {time}")
                        return value
                    else:
                        logging.warning(f"No record found for timestamp {time}")
                        return None
        except Exception as e:
            logging.error(f"Error fetching record for timestamp {time}: {e}")
            return None
        
    async def process_files_in_batches(self):
        """Process and upload files from the working directory in batches."""
        files = [f for f in os.listdir(self.working_dir) if f.endswith('.mp3')]
        batch_size = 5  # Maximum number of files per batch
        for i in range(0, len(files), batch_size):
            batch = files[i:i+batch_size]
            try:
                documents = await self.prepare_documents(batch)
                if documents:
                    result = await self.db[self.collection_name].insert_many(documents)
                    if result.acknowledged:
                        logging.info(f"{len(documents)} documents inserted into the collection.")
                        # Only delete files if all documents were successfully inserted
                        for doc in documents:
                            os.remove(os.path.join(self.working_dir, doc['filename']))
            except Exception as e:
                logging.error(f"Error processing batch starting with {batch[0]}: {e}")
        
    async def prepare_documents(self, filenames):
        """Prepare document list from filenames for batch insertion."""
        documents = []
        for filename in filenames:
            filepath = os.path.join(self.working_dir, filename)
            try:
                timestamp = self.extract_timestamp(filename)
                database_value = await self.fetch_record("LAeq", "LAeq1min", timestamp)

                # Check if database_value and audio_trigger are not None
                if database_value is not None and self.audio_trigger is not None:
                    # Ensure both are of numeric type
                    if isinstance(database_value, (int, float)) and isinstance(self.audio_trigger, (int, float)):
                        if database_value >= self.audio_trigger:
                            # Proceed with processing
                            with open(filepath, 'rb') as file:
                                binary_data = file.read()
                            documents.append({
                                'filename': filename,
                                'audio_data': binary_data,
                                'timestamp': timestamp
                            })
                        else:
                            logging.info(f"Fetched value {database_value} is less than audio trigger {self.audio_trigger}. Deleting file {filename}.")
                            os.remove(filepath)
                    else:
                        logging.error(f"Invalid types for comparison. database_value: {database_value} (type: {type(database_value)}), audio_trigger: {self.audio_trigger} (type: {type(self.audio_trigger)}). Deleting file {filename}.")
                        os.remove(filepath)
                else:
                    logging.warning(f"database_value or audio_trigger is None for {filename}. Deleting file.")
                    os.remove(filepath)
            except Exception as e:
                logging.error(f"Failed to read or prepare file {filename}: {e}")
        return documents
    
    async def process_files(self):
        """Process and upload files from the working directory."""
        files = [f for f in os.listdir(self.working_dir) if f.endswith('.mp3')]
        for filename in files:
            await self.process_and_upload_file(filename)

    async def process_and_upload_file(self, filename):
        """Process a single audio file and upload it to MongoDB."""
        filepath = os.path.join(self.working_dir, filename)
        try:
            timestamp = self.extract_timestamp(filename)
            database_value = await self.fetch_record("LAeq", "LAeq1min", timestamp)

            if database_value is not None:
                if database_value >= self.audio_trigger:
                    #logging.info(f"Fetched value {database_value} meets or exceeds audio trigger {self.audio_trigger}")

                    with open(filepath, 'rb') as file:
                        binary_data = file.read()  # Consider chunked reading if files are large

                    # Construct the document to insert into MongoDB
                    document = {
                        'filename': filename,
                        'audio_data': binary_data,
                        'timestamp': timestamp
                    }

                    # Insert document into MongoDB
                    result = await self.db[self.collection_name].insert_one(document)
                    if result.acknowledged:
                        logging.info(f"Audio document successfully inserted: {filename} with ID {result.inserted_id}")
                        os.remove(filepath)  # Remove the file after successful upload
                    else:
                        logging.error(f"MongoDB did not acknowledge the insert for {filename}")
                else:
                    #logging.info(f"Fetched value {database_value} is less than audio trigger {self.audio_trigger}. Deleting file {filename}.")
                    os.remove(filepath)
            else:
                logging.warning(f"No database value found for {filename} with timestamp {timestamp}. Deleting file.")
                os.remove(filepath)

        except Exception as e:
            logging.error(f"Failed to process and upload {filename}: {e}")

    def extract_timestamp(self, filename):
        """Extract timestamp from filename."""
        timestamp_str = filename.replace('.mp3', '')
        return datetime.strptime(timestamp_str, '%Y-%m-%d %H-%M-%S')
    
    async def run(self):
        await self.ensure_collection_exists()
        await self.initialize_audio_trigger()

        watch_task = asyncio.create_task(self.watch_audio_trigger_changes())

        try:
            while True:
                current_file_count = self.scan_directory()

                if current_file_count > 5:
                    logging.info(f"Processing in batches due to high volume of {current_file_count} files.")
                    await self.process_files_in_batches()  # Assume this processes batches of 5
                    await asyncio.sleep(3)  # Pause between batches to reduce load
                elif current_file_count > 0:
                    logging.info(f"Processing {current_file_count} files individually.")
                    await self.process_files()  # Process all available files
                    await asyncio.sleep(40)  # Wait for one minute if the file count is low
                else:
                    logging.info("No files to process. Waiting for new files.")
                    await asyncio.sleep(40)

        except Exception as e:
            logging.error(f"Unexpected error in run method of AudioTransfer: {e}")
        except asyncio.CancelledError:
            logging.info("AudioTransfer task was cancelled")
        finally:
            watch_task.cancel()
            #await self.stop()

    async def watch_audio_trigger_changes(self):
        """Monitor the 'audio_trigger' field for changes and update internally."""
        try:
            async with self.document_status.watch([
                {'$match': {'documentKey._id': self.device_id, 'operationType': 'update', 'updateDescription.updatedFields.audio_trigger': {'$exists': True}}}
            ]) as stream:
                async for change in stream:
                    new_trigger_value = change['updateDescription']['updatedFields'].get('audio_trigger')
                    if new_trigger_value != self.audio_trigger:
                        self.audio_trigger = new_trigger_value
        except Exception as e:
            logging.error(f"Error watching battery changes: {str(e)}")

    async def stop(self):
        """Cleanly shut down the data transfer, ensuring all resources are properly released."""
        # Attempt to close the MongoDB client connection if had not already been closed
        if self.mongo_client is not None:
            try:
                self.mongo_client.close()
                logging.info("MongoDB client connection successfully closed.")
            except Exception as e:
                logging.error(f"Error closing MongoDB client connection: {e}")