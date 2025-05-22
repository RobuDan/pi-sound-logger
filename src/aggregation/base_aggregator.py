import logging

class BaseAggregator:
    def __init__(self, param, connection_pool, time_manager):
        self.param = param
        self.connection_pool = connection_pool
        self.time_manager = time_manager
        self.intervals = []
        
    def subscribe_to_intervals(self, intervals):
        for interval in intervals:
            self.time_manager.subscribe(interval, self)
            self.intervals.append(interval)
            # logging.info(f"{self.__class__.__name__} subscribed to {interval} interval")

    async def notifyAboutInterval(self, interval, start_time, end_time):
        # Placeholder method to be overridden by subclasses
        #logging.info(f"{self.__class__.__name__} notified for {interval} interval: Start Time - {start_time}, End Time - {end_time}")
        raise NotImplementedError("Subclass must implement its own interval handling logic.")
    
    async def aggregate(self, start_time, end_time):
            # To be overridden by subclasses with specific aggregation logic
            logging.info(f"Aggregating data for {self.db_path}. This method should be overridden.")
            raise NotImplementedError("Subclass must implement its own aggregation logic.")


