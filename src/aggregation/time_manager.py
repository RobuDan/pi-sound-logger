import asyncio
import logging
from datetime import datetime, timedelta

class TimeManager:
    def __init__(self):
        self.subscribers = {
            '1min': [],
            '5min': [],
            '15min': [],
            '30min': [],
            '1h': [],
            '24h': []
        }
        self.shutdown_flag = False

    async def start(self):
        logging.info("TimeManager started.")
        while not self.shutdown_flag:
            await self._tick()
            await asyncio.sleep(1)  # Check every second

    async def _tick(self):
        current_time = datetime.now()
        # logging.info(f"[TimeManager] Tick at {current_time.strftime('%H:%M:%S.%f')}")
        for interval, subscribers in self.subscribers.items():
            if self._is_interval(current_time, interval):
                await self._notify_subscribers(subscribers, current_time, interval)

    async def _notify_subscribers(self, subscribers, current_time, interval):
        end_time = current_time.replace(microsecond=0)
        start_time = {
            '1min': end_time - timedelta(minutes=1),
            '5min': end_time - timedelta(minutes=5),
            '15min': end_time - timedelta(minutes=15),
            '30min': end_time - timedelta(minutes=30),
            '1h': end_time - timedelta(hours=1),
            '24h': end_time - timedelta(hours=24)
        }.get(interval, end_time)

        logging.info(f"Interval {interval} triggered. Start: {start_time}, End: {end_time}")

        for subscriber in subscribers:
            try:
                #logging.info(f"Notifying {subscriber} for {interval}")
                # Notify the subscriber, passing both the start and end time
                await subscriber.notifyAboutInterval(interval, start_time, end_time)
            except Exception as e:
                logging.error(f"Error notifying subscriber: {e}")

    def _is_interval(self, current_time, interval):
        if interval == '1min' and current_time.second == 0:
            return True
        elif interval == '5min' and current_time.minute % 5 == 0 and current_time.second == 0:
            return True
        elif interval == '15min' and current_time.minute % 15 == 0 and current_time.second == 0:
            return True
        elif interval == '30min' and current_time.minute % 30 == 0 and current_time.second == 0:
            return True
        elif interval == '1h' and current_time.minute == 0 and current_time.second == 0:
            return True
        elif interval == '24h' and current_time.hour == 0 and current_time.minute == 0 and current_time.second == 0:
            return True
        return False

    def subscribe(self, interval, subscriber):
        # Add a subscriber to a time interval
        if interval in self.subscribers:
            self.subscribers[interval].append(subscriber)
        else:
            logging.error(f"Attempted to subscribe to unknown interval: {interval}")

    def unsubscribe(self, interval, subscriber):
        # Remove a subscriber from a time interval
        if interval in self.subscribers:
            self.subscribers[interval].remove(subscriber)

    async def stop(self):
        self.shutdown_flag = True
        logging.info("TimeManager stopped.")