import os
import asyncpg
import logging

logger = logging.getLogger("database")

DATABASE_URL = os.getenv("DATABASE_URL")

_pool = None


# ==================================================
# INIT DATABASE
# ==================================================

async def init_db():
    global _pool

    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL not set")

    logger.info("Initializing PostgreSQL connection pool...")

    try:
        _pool = await asyncpg.create_pool(DATABASE_URL)

        # Quick connection test
        async with _pool.acquire() as conn:
            version = await conn.fetchval("SELECT version();")
            logger.info("Connected to PostgreSQL successfully.")
            logger.debug("Postgres version: %s", version)

    except Exception as e:
        logger.exception("Failed to create DB pool: %s", e)
        raise

    async with _pool.acquire() as conn:

        # -----------------------------
        # STREAMERS TABLE
        # -----------------------------
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS streamers (
                guild_id TEXT NOT NULL,
                broadcaster_id TEXT NOT NULL,
                channel_id TEXT NOT NULL,
                is_live BOOLEAN DEFAULT FALSE,
                PRIMARY KEY (guild_id, broadcaster_id)
            );
        """)

        # -----------------------------
        # FREE GAMES TABLE
        # -----------------------------
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS free_games (
                platform TEXT NOT NULL,
                title TEXT NOT NULL,
                url TEXT NOT NULL,
                thumbnail TEXT,
                updated_at TIMESTAMP DEFAULT NOW(),
                PRIMARY KEY (platform, title)
            );
        """)

        # DEBUG: count existing streamers
        count = await conn.fetchval("SELECT COUNT(*) FROM streamers;")
        logger.info("Streamers table ready. Current row count: %s", count)

    logger.info("Database initialized (streamers + free_games)")


# ==================================================
# GET POOL
# ==================================================

def get_pool():
    if _pool is None:
        logger.error("Database pool requested but not initialized!")
    return _pool


# ==================================================
# DEBUG UTILITY (Optional)
# ==================================================

async def debug_list_streamers():
    """
    Temporary debug helper.
    Logs all streamers currently stored in DB.
    """
    if _pool is None:
        logger.error("Cannot debug DB — pool not initialized.")
        return

    async with _pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT guild_id, broadcaster_id, channel_id, is_live
            FROM streamers;
        """)

    if not rows:
        logger.info("DEBUG: No streamers found in DB.")
        return

    logger.info("DEBUG: Current streamers in DB:")
    for r in rows:
        logger.info(
            "Guild=%s | Broadcaster=%s | Channel=%s | Live=%s",
            r["guild_id"],
            r["broadcaster_id"],
            r["channel_id"],
            r["is_live"]
        )
