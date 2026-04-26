import os
import asyncio
import logging
import importlib

from .time_manager import TimeManager
from .acoustic_aggregator.uncertainty_calculator import UncertaintyCalculator

class AggregationManager:
    def __init__(self, audio_config, connection_pool, weather_enabled=False):
        self.config = audio_config
        self.connection_pool = connection_pool
        self.weather_enabled = weather_enabled
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
        await self._load_acoustic_aggregators()

        if self.weather_enabled:
            await self._load_weather_aggregators()

    async def _load_acoustic_aggregators(self):
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

                    if param == "LAeq":
                        incert_calc = UncertaintyCalculator(param, self.connection_pool, self.time_manager, self.weather_enabled)
                        self.aggregators.append(incert_calc)

                        
                except (ImportError, AttributeError) as e:
                    logging.error(f"Error loading aggregator for {param}: {e}")

    async def _load_weather_aggregators(self):
        try:
            module_name = "aggregation.weather_aggregator.weather_aggregator"
            class_name = "WeatherAggregator"

            module = importlib.import_module(module_name)
            class_ = getattr(module, class_name)

            aggregator = class_(self.connection_pool, self.time_manager)
            self.aggregators.append(aggregator)

            logging.info("Weather aggregator loaded successfully.")

        except (ImportError, AttributeError) as e:
            logging.error(
                f"Error loading aggregator for weather aggregation {e}"
            )


    async def stop(self):
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
