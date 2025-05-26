import os
import json
import pytz
import datetime
import asyncio
import logging
import aiohttp
import nsrt_mk3_dev
from pymongo.change_stream import ChangeStream
from pymongo.errors import OperationFailure

from utils.json_config_loader import LoadConfiguration
from utils.env_config_loader import Config

class MicrophoneDetails:
    def __init__(self, device, mongo_client, data_base_status, callback):
        self.device = device                 # Initially None. Set later when device is detected. Getting instance of nsrt_mk3_dev.NsrtMk3Dev
        self.serial_number = Config.SERIAL_NUMBER       # Statically loaded from config for registration clarity. 
        self.parameters = None
        self.device_id = Config.SERIAL_NUMBER  # Static ID for registration consistency
        self.mongo_client = mongo_client
        self.data_base_status = data_base_status
        self.db = self.mongo_client[self.data_base_status]
        self.callback = callback
        self.collection_name = 'microphones'
        self.callback_in_progress = False

    def update_device(self, new_device):
        self.device = new_device

    async def ensure_collection_exists(self):
            try:
                existing_collections = await self.db.list_collection_names()
                if self.collection_name not in existing_collections:
                    await self.db.create_collection(self.collection_name)
            except OperationFailure as e:
                if e.code == 8000:  # Specific error code for permissions
                    logging.error(f"Permission error: {e.details['errmsg']}")
                    logging.error("Please ensure the MongoDB user has 'listCollections' and 'createCollection' privileges.")
                else:
                    logging.error(f"Operation failed: {e.details}")
            except Exception as e:
                logging.error(f"Error ensuring collection exists in '{self.data_base_status}': {str(e)}")


    async def create_initial_device_document(self):
        """
        Create or update the initial MongoDB document for this device,
        using device methods to retrieve metadata if available.
        """
        bucharest_tz = pytz.timezone('Europe/Bucharest')
        now_bucharest = datetime.datetime.now(bucharest_tz)

        model, firmware, dob, doc = None, None, None, None
        if self.device:
            try:
                model = await asyncio.to_thread(self.device.read_model)
                firmware = await asyncio.to_thread(self.device.read_fw_rev)
                dob = await asyncio.to_thread(self.device.read_dob)
                doc = await asyncio.to_thread(self.device.read_doc)
            except Exception as e:
                logging.warning(f"Could not read device metadata from serial: {e}")

        existing_doc = await self.db[self.collection_name].find_one({"_id": self.device_id})
        if existing_doc is None:
            document_fields = {
                "_id": self.device_id,
                "serial_number": self.serial_number,  # Static from config
                "type": model,
                "firmware": firmware,
                "manufacturing_date": dob,
                "calibration_date": doc,
                "factory_verified": None,
                "longitude": None,
                "latitude": None,
                "altitude": None,
                "state": "Running" if self.device else "Inactive",
                "temperature": None,
                "battery": {
                    "current": None,
                    "charged": None,
                    "timeremaining": None
                },
                "parameters": self.parameters,
                "audio_trigger": 70,
                "updated_parameters": {
                    "AcousticSequences": None,
                    "SpectrumSequences": None,
                    "AudioSequences": None
                },
                "last_updated": now_bucharest
            }
            try:
                await self.db[self.collection_name].insert_one(document_fields)
                logging.info(f"New device document created for _id: {self.device_id}")
            except Exception as e:
                logging.error(f"Error creating device document: {e}")

        else:
            # Only update runtime fields
            update_fields = {
                "serial_number": self.serial_number,  # Static from config
                "type": model,
                "firmware": firmware,
                "manufacturing_date": dob,
                "calibration_date": doc,
                "state": "Running" if self.device else "Inactive",
                "battery":{"current": None, "charged": None, "timeremaining": None},
                "parameters": self.parameters,
                "updated_parameters": {"AcousticSequences": None, "SpectrumSequences": None, "AudioSequences": None},
                "last_updated": now_bucharest
            }
            try:
                await self.db[self.collection_name].update_one(
                    {"_id": self.device_id},
                    {"$set": update_fields}
                )
                logging.info(f"Existing device document updated for _id: {self.device_id}")
            except Exception as e:
                logging.error(f"Error creating/updating device document: {e}")


    async def update_microphone_document(self):
        """
        Push latest live info (temperature, state, etc.) to MongoDB.
        """
        update_fields = {
            "state": self.state,
            "temperature": self.temperature,
            "battery": {
                "current": None,
                "charged": None,
                "timeremaining": None
            },
            "altitude": None,
            "latitude": None,
            "longitude": None,
            "last_updated": datetime.datetime.now(pytz.timezone('Europe/Bucharest'))
        }

        try:
            await self.db[self.collection_name].update_one(
                {"_id": self.device_id},
                {"$set": update_fields}
            )
        except Exception as e:
            logging.error(f"Error updating device document: {e}")

    async def fetch_and_update_microphone_status(self):
        """
        Update dynamic status info (e.g., temperature) from device and push to MongoDB.
        """
        if self.device is None:
            self.state = "Inactive"
            self.temperature = None
        else:
            try:
                self.state = "Running"
                if self.device:
                    self.temperature = await asyncio.to_thread(self.device.read_temperature)
            except Exception as e:
                logging.warning(f"Error reading temperature or state: {e}")
                self.temperature = None
                self.state = "Inactive"

        await self.update_microphone_document()


    async def reset_updated_parameters(self, updated_params):
        """Reset the updated_parameters in the document to None after processing."""
        reset_values = {
            "AcousticSequences": None,
            "SpectrumSequences": None,
            "AudioSequences": None
        }
        try:
            result = await self.db[self.collection_name].update_one(
                {"_id": self.device_id},
                {"$set": {"updated_parameters": reset_values}}
            )
            if result.modified_count:
                #logging.info("Updated parameters have been reset to initial state.")
                await self.handle_updated_parameters(updated_params)
            else:
                logging.info("No changes made to updated parameters (possibly already reset).")
        except Exception as e:
            logging.error(f"Error resetting updated_parameters: {str(e)}")

    async def handle_updated_parameters(self, updated_params):
        """Process updated parameters: delete old and create new parameters.json with updated values."""
        parameters_path = 'config/parameters.json'

        new_parameters = {}
        for key, value in updated_params.items():
            if isinstance(value, list):
                # Directly assign if already a list
                new_parameters[key] = value
            else:
                # Wrap in a list if it's a single non-list value
                new_parameters[key] = [value] if value is not None else []
        try:
            os.remove(parameters_path)
            #logging.info("parameters.json file has been deleted successfully.")
        except OSError as e:
            logging.error(f"Error deleting parameters.json: {str(e)}")
            return  # Exit if file deletion fails to prevent creation of incorrect config file

        # Write the new parameters to a new parameters.json file
        try:
            with open(parameters_path, 'w') as file:
                json.dump(new_parameters, file, indent=4)
            #logging.info("New parameters.json file has been created successfully with updated parameters.")
            if self.callback and not self.callback_in_progress:
                self.callback_in_progress = True
                asyncio.create_task(self.handle_callback())
        except Exception as e:
            logging.error(f"Error creating new parameters.json: {str(e)}")

    async def handle_callback(self):
        try:
            if self.callback:
                await self.callback()
        finally:
            self.callback_in_progress = False

    async def update_parameters(self, updated_params):
        """Update the regular parameters with the new set, ensuring correct data formatting."""
        if all(value is None for value in updated_params.values()):
            logging.info("All updated parameters are None, skipping update.")
            return

        # Ensure each parameter is a list, even if it's a single value or None
        new_parameters = {
            "parameters": {
                "AcousticSequences": updated_params.get('AcousticSequences') if isinstance(updated_params.get('AcousticSequences'), list) else [updated_params.get('AcousticSequences')] if updated_params.get('AcousticSequences') else [],
                "SpectrumSequences": updated_params.get('SpectrumSequences') if isinstance(updated_params.get('SpectrumSequences'), list) else [updated_params.get('SpectrumSequences')] if updated_params.get('SpectrumSequences') else [],
                "AudioSequences": updated_params.get('AudioSequences') if isinstance(updated_params.get('AudioSequences'), list) else [updated_params.get('AudioSequences')] if updated_params.get('AudioSequences') else []
            }
        }

        logging.info(f"Attempting to update document with: {new_parameters}")
        try:
            result = await self.db[self.collection_name].update_one(
                {"_id": self.device_id},
                {"$set": new_parameters}
            )
            if result.modified_count:
                logging.info("Document successfully updated with new parameters.")
            else:
                logging.info("No document was modified — likely no change in data.")
        except Exception as e:
            logging.error(f"Error updating device document in function update_parameters: {str(e)}")

    async def watch_document_for_parameters_change(self):
        """Watch for changes to the updated_parameters in the document."""
        pipeline = [
            {
                '$match': {
                    'documentKey._id': self.device_id,
                    'operationType': 'update',
                    'updateDescription.updatedFields.updated_parameters': {'$exists': True}  # Watching for changes in updated_parameters
                }
            }
        ]
        try:
            async with self.db[self.collection_name].watch(pipeline) as stream:
                async for change in stream:
                    updated_params = change['updateDescription']['updatedFields'].get('updated_parameters')
                    if updated_params:
                        logging.info(f"Detected change in updated_parameters: {updated_params}")
                        await self.update_parameters(updated_params)
                        await self.reset_updated_parameters(updated_params)
                        #await self.handle_updated_parameters(updated_params)
        except Exception as e:
            logging.error(f"Error watching battery changes: {str(e)}")

    async def run(self):
        await self.ensure_collection_exists()
        loader = LoadConfiguration()

        _,  self.parameters = loader.load_config('config/parameters.json')

        try:
            await self.create_initial_device_document()
            watcher_task = asyncio.create_task(self.watch_document_for_parameters_change())
            while True:
                await self.fetch_and_update_microphone_status()
                await asyncio.sleep(25)
        except Exception as e:
            logging.error(f"Unexpected error in run method of StatusMicrophone: {e}")
        except asyncio.CancelledError:
            logging.info("StatusMicrohpone task was cancelled")
        finally:

            if watcher_task:
                watcher_task.cancel()
                
