import aiomysql
import numpy as np

async def fetch_acoustic_data(connection_pool, db_name, table_name, start_time, end_time):
    records = {}
    async with connection_pool.acquire() as conn:
        await conn.select_db(db_name)
        async with conn.cursor() as cur:
            fetch_sql = f"""
            SELECT timestamp, value FROM `{table_name}`
            WHERE timestamp >= %s AND timestamp < %s;
            """
            await cur.execute(fetch_sql, (start_time, end_time))
            rows = await cur.fetchall()
            records = {row[0]: row[1] for row in rows}
    return records

async def fetch_weather_data(connection_pool, db_name, table_name, start_time, end_time):
    records = {}
    async with connection_pool.acquire() as conn:
        await conn.select_db(db_name)
        async with conn.cursor() as cur:
            fetch_sql = f"""
            SELECT timestamp, wind_speed, wind_direction FROM `{table_name}`
            WHERE timestamp >= %s AND timestamp < %s;
            """
            await cur.execute(fetch_sql, (start_time, end_time))
            rows = await cur.fetchall()
            records = {row[0]: (row[1], row[2]) for row in rows}
    return records

async def fetch_laf_data(connection_pool, db_name, table_name, start_time, end_time):
    async with connection_pool.acquire() as conn:
        await conn.select_db(db_name)
        async with conn.cursor() as cur:
            await cur.execute(
                f"""
                SELECT value FROM `{table_name}`
                WHERE timestamp >= %s AND timestamp < %s;
                """,
                (start_time, end_time),
            )
            rows = await cur.fetchall()

    if not rows:
        return None

    # Convert to array
    arr = np.array([row[0] for row in rows], dtype=float)

    # Clean 
    arr = arr[np.isfinite(arr)]

    if arr.size == 0:
        return None

    return arr