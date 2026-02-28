import os
import asyncpg
import logging

logger = logging.getLogger("database")


class Database:

    def __init__(self, dsn: str):
        self.dsn = dsn
        self.pool: asyncpg.Pool | None = None

    async def connect(self):

        if self.pool:
            return

        logger.info("Creating PostgreSQL pool...")

        self.pool = await asyncpg.create_pool(
            self.dsn,
            min_size=2,
            max_size=10,
            command_timeout=30
        )

        async with self.pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS streamers (
                    guild_id TEXT NOT NULL,
                    broadcaster_id TEXT NOT NULL,
                    channel_id TEXT NOT NULL,
                    is_live BOOLEAN DEFAULT FALSE,
                    PRIMARY KEY (guild_id, broadcaster_id)
                );
            """)

        logger.info("Database initialized.")

    async def close(self):

        if self.pool:
            await self.pool.close()
            self.pool = None
            logger.info("Database pool closed.")

    def get_pool(self) -> asyncpg.Pool:
        if not self.pool:
            raise RuntimeError("Database not initialized.")
        return self.pool
