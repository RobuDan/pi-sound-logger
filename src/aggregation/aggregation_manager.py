import os
import asyncio
import logging
import importlib

from .time_manager import TimeManager

class AggregationManager:
    def __init__(self, config, connection_pool):
        self.config = config
        self.connection_pool = connection_pool
        self.time_manager = TimeManager()
        self.aggregators = []
        self.tasks = []
    
    async def start(self):
        await self._load_aggregators()
        self.tasks.append(asyncio.create_task(self.time_manager.start()))

        for aggregator in self.aggregators:
            self.tasks.append(asyncio.create_task(aggregator.aggregate()))
        logging.info(f"Loaded configuration: {self.config}")

    async def _load_aggregators(self):
        sequence_types = {
            'AcousticSequences': "aggregation.acoustic_aggregator",
            # 'SpectrumSequences': "DataAggregation.SpectrumAggregation"
        }
        
        for sequence_type, base_path in sequence_types.items():
            for param in self.config.get(sequence_type, []):
                try:
                    # Construct the module name based on the sequence type and parameter
                    module_name = f"{base_path}.{param.lower()}_aggregator"
                    class_name = f"{param}Aggregator"

                    # Dynamically import the module and class
                    module = importlib.import_module(module_name)
                    class_ = getattr(module, class_name)

                    aggregator = class_(param, self.connection_pool, self.time_manager)
                    self.aggregators.append(aggregator)

                except (ImportError, AttributeError) as e:
                    logging.error(f"Error loading aggregator for {param}: {e}")

    async def manager_stop(self):
        logging.info(f"Stopping AggregationManager and it's tasks...")
        for task in self.tasks:
            task.cancel()

        results = await asyncio.gather(*self.tasks, return_exceptions=True)
        for result, task in zip(results, self.tasks):
            if isinstance(result, Exception):
                logging.error(f"Error while stopping task {task}: {result}")
            else:
                logging.info(f"Task {task} stopped successfully.")
        logging.info("Aggregation manager stopped.")
