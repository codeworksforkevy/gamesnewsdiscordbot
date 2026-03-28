"""
db/pool.py
────────────────────────────────────────────────────────────────
Global asyncpg connection pool.

Improvements over original:
- command_timeout added to prevent hanging queries
- close_pool registered as an atexit hook automatically on init,
  so callers don't have to remember to call it on shutdown
"""

import atexit
import asyncio
import logging
import os
from typing import Optional

import asyncpg

logger = logging.getLogger("db.pool")

_pool: Optional[asyncpg.Pool] = None

# How long (seconds) a single query may run before being cancelled
COMMAND_TIMEOUT = 30


# ──────────────────────────────────────────────────────────────
# LIFECYCLE
# ──────────────────────────────────────────────────────────────

async def init_pool() -> asyncpg.Pool:
    """
    Initializes and returns the global DB pool.
    Safe to call multiple times — returns the existing pool if already open.
    """
    global _pool

    if _pool:
        logger.warning("DB pool already initialized — returning existing pool")
        return _pool

    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL environment variable is not set")

    try:
        _pool = await asyncpg.create_pool(
            dsn=database_url,
            min_size=1,
            max_size=10,
            timeout=30,
            command_timeout=COMMAND_TIMEOUT,
        )

        logger.info("Database pool initialized")

        # Register graceful shutdown automatically
        atexit.register(_sync_close_pool)

    except Exception:
        logger.exception("Failed to initialize DB pool")
        raise

    return _pool


async def get_pool() -> asyncpg.Pool:
    if not _pool:
        raise RuntimeError(
            "DB pool is not initialized — call await init_pool() first"
        )
    return _pool


async def close_pool() -> None:
    global _pool

    if _pool:
        await _pool.close()
        _pool = None
        logger.info("Database pool closed")


def _sync_close_pool() -> None:
    """atexit-compatible synchronous wrapper for close_pool."""
    if _pool:
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(close_pool())
            else:
                loop.run_until_complete(close_pool())
        except Exception as e:
            logger.warning(f"Pool close on exit failed: {e}")
