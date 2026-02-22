import os
import asyncpg
import logging

logger = logging.getLogger("database")

DATABASE_URL = os.getenv("DATABASE_URL")

_pool = None


async def init_db():
    global _pool

    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL not set")

    _pool = await asyncpg.create_pool(DATABASE_URL)

    async with _pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS streamers (
                guild_id TEXT NOT NULL,
                broadcaster_id TEXT NOT NULL,
                channel_id TEXT NOT NULL,
                is_live BOOLEAN DEFAULT FALSE,
                PRIMARY KEY (guild_id, broadcaster_id)
            );
        """)

    logger.info("Database initialized")


async def get_pool():
    return _pool
