import logging

import math
import asyncio
import aiomysql

from aggregation.base_aggregator import BaseAggregator
from .weather_aggregation_config import (
    AGGREGATION_RULES,
    TARGET_TABLES,
    COLUMN_TYPES,
)
from utils.env_config_loader import Config


class WeatherAggregator(BaseAggregator):
    DEFAULT_DB_NAME = "weather"
    SOURCE_TABLE_1MIN = "weather1min"

    def __init__(self, connection_pool, time_manager, param=None):
        db_name = param or self.DEFAULT_DB_NAME
        super().__init__(db_name, connection_pool, time_manager)

        self.db_name = db_name
        self.source_table_1min = self.SOURCE_TABLE_1MIN
        self.interval_delay_seconds = 5
        self.data_retention_days = Config.MYSQL_DATA_RETENTION

        self.subscribe_to_intervals(["5min", "15min", "30min", "1h", "24h"])

    async def notifyAboutInterval(self, interval, start_time, end_time):
        target_table = TARGET_TABLES.get(interval)
        await asyncio.sleep(self.interval_delay_seconds)

        logging.info(
            f"WeatherAggregator notified for {interval}: "
            f"start={start_time}, end={end_time}"
        )

        rows = await self.fetch_records(
            self.db_name,
            self.source_table_1min,
            start_time,
            end_time,
        )

        if not rows:
            logging.warning(
                f"WeatherAggregator found no rows for {interval}: "
                f"start={start_time}, end={end_time}, "
                f"source={self.source_table_1min}"
            )
            return

        aggregated_data = self.aggregate_rows(rows)

        if not aggregated_data:
            logging.warning(
                f"WeatherAggregator produced no aggregated data for {interval}: "
                f"start={start_time}, end={end_time}"
            )
            return

        await self.insert_aggregated_row(
            self.db_name,
            target_table,
            start_time,
            aggregated_data,
        )

        logging.info(
            f"WeatherAggregator inserted aggregated row for {interval}: "
            f"timestamp={start_time}, target={target_table}, {aggregated_data}"
        )

    async def aggregate(self):
        pass

    async def fetch_records(self, db_name, table_name, start_time, end_time):
        columns_sql = ", ".join(f"`{col}`" for col in AGGREGATION_RULES.keys())

        fetch_sql = f"""
        SELECT {columns_sql}
        FROM `{table_name}`
        WHERE timestamp >= %s AND timestamp < %s
        ORDER BY timestamp ASC;
        """

        async with self.connection_pool.acquire() as conn:
            await conn.select_db(db_name)
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(fetch_sql, (start_time, end_time))
                rows = await cur.fetchall()

        return rows

    def aggregate_rows(self, rows):
        accumulators = self._init_accumulators()

        for row in rows:
            for column, rule in AGGREGATION_RULES.items():
                value = row.get(column)

                if value is None:
                    continue

                if rule == "avg":
                    accumulators[column]["sum"] += float(value)
                    accumulators[column]["count"] += 1

                elif rule == "sum":
                    accumulators[column]["sum"] += float(value)

                elif rule == "max":
                    if accumulators[column]["value"] is None:
                        accumulators[column]["value"] = value
                    else:
                        accumulators[column]["value"] = max(
                            accumulators[column]["value"],
                            value,
                        )

                elif rule == "circular_mean":
                    angle = float(value) % 360
                    radians = math.radians(angle)
                    accumulators[column]["sin_sum"] += math.sin(radians)
                    accumulators[column]["cos_sum"] += math.cos(radians)
                    accumulators[column]["count"] += 1

                else:
                    raise ValueError(f"Unsupported aggregation rule: {rule}")

        return self._finalize_accumulators(accumulators)

    def _init_accumulators(self):
        accumulators = {}

        for column, rule in AGGREGATION_RULES.items():
            if rule == "avg":
                accumulators[column] = {"sum": 0.0, "count": 0}
            elif rule == "sum":
                accumulators[column] = {"sum": 0.0}
            elif rule == "max":
                accumulators[column] = {"value": None}
            elif rule == "circular_mean":
                accumulators[column] = {
                    "sin_sum": 0.0,
                    "cos_sum": 0.0,
                    "count": 0,
                }
            else:
                raise ValueError(f"Unsupported aggregation rule: {rule}")

        return accumulators

    def _finalize_accumulators(self, accumulators):
        result = {}

        for column, rule in AGGREGATION_RULES.items():
            acc = accumulators[column]

            if rule == "avg":
                if acc["count"] == 0:
                    result[column] = None
                else:
                    value = acc["sum"] / acc["count"]
                    result[column] = self._cast_output(column, value)

            elif rule == "sum":
                result[column] = self._cast_output(column, acc["sum"])

            elif rule == "max":
                result[column] = self._cast_output(column, acc["value"])

            elif rule == "circular_mean":
                if acc["count"] == 0:
                    result[column] = None
                else:
                    angle = math.degrees(
                        math.atan2(acc["sin_sum"], acc["cos_sum"])
                    )
                    if angle < 0:
                        angle += 360
                    result[column] = self._cast_output(column, angle)

        return result

    def _cast_output(self, column, value):
        if value is None:
            return None

        if column in {"out_humi", "in_humi", "wind_direction", "is_raining"}:
            return int(round(value))

        return round(float(value), 2)

    async def insert_aggregated_row(self, db_name, table_name, timestamp, aggregated_data):
        await self._create_table_if_not_exists(db_name, table_name)

        columns = ["timestamp", *aggregated_data.keys(), "is_sent", "is_aggregated"]
        column_sql = ", ".join(f"`{col}`" for col in columns)
        placeholders = ", ".join(["%s"] * len(columns))

        values = [timestamp, *aggregated_data.values(), 0, 0]

        insert_sql = f"""
        INSERT INTO `{table_name}` ({column_sql})
        VALUES ({placeholders});
        """

        async with self.connection_pool.acquire() as conn:
            await conn.select_db(db_name)
            async with conn.cursor() as cur:
                await cur.execute(insert_sql, values)
                await conn.commit()

    async def _create_table_if_not_exists(self, db_name, table_name):
        column_defs = []
        for column in AGGREGATION_RULES.keys():
            column_defs.append(f"`{column}` {COLUMN_TYPES[column]}")

        columns_sql = ",\n            ".join(column_defs)

        create_table_sql = f"""
        CREATE TABLE IF NOT EXISTS `{table_name}` (
            id INT PRIMARY KEY AUTO_INCREMENT,
            timestamp TIMESTAMP NOT NULL,
            {columns_sql},
            is_sent TINYINT NOT NULL DEFAULT 0,
            is_aggregated TINYINT NOT NULL DEFAULT 0,
            INDEX idx_timestamp (timestamp),
            INDEX idx_is_sent (is_sent),
            INDEX idx_is_aggregated (is_aggregated),
            INDEX idx_is_sent_is_aggregated (is_sent, is_aggregated)
        );
        """

        create_event_sql = f"""
        CREATE EVENT IF NOT EXISTS `ev_delete_old_data_{table_name}`
        ON SCHEDULE EVERY 1 DAY
        DO
            DELETE FROM `{table_name}`
            WHERE timestamp < NOW() - INTERVAL {self.data_retention_days} DAY;
        """

        async with self.connection_pool.acquire() as conn:
            await conn.select_db(db_name)
            async with conn.cursor() as cur:
                await cur.execute(create_table_sql)
                await cur.execute(create_event_sql)
                await conn.commit()