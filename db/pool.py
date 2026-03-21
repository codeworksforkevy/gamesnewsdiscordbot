# db/pool.py

import os
import logging
import asyncpg
from typing import Optional

logger = logging.getLogger("db.pool")

_pool: Optional[asyncpg.Pool] = None


async def init_pool():
    """
    Initialize global DB pool.
    Railway uyumlu: DATABASE_URL kullanır.
    """
    global _pool

    if _pool:
        logger.warning("DB pool already initialized")
        return _pool

    database_url = os.getenv("DATABASE_URL")

    if not database_url:
        raise RuntimeError("DATABASE_URL is not set")

    try:
        _pool = await asyncpg.create_pool(
            dsn=database_url,
            min_size=1,
            max_size=10,
            timeout=30
        )

        logger.info("Database pool initialized")

    except Exception as e:
        logger.exception("Failed to initialize DB pool")
        raise e

    return _pool


async def get_pool() -> asyncpg.Pool:
    if not _pool:
        raise RuntimeError("DB pool is not initialized")
    return _pool


async def close_pool():
    global _pool

    if _pool:
        await _pool.close()
        _pool = None
        logger.info("Database pool closed")
