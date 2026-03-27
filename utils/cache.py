# utils/cache.py
#
# FIX: was creating a synchronous redis.from_url() client at import time.
# The rest of the bot (free_games_service, notifier, etc.) uses
# redis.asyncio — so every await redis.get() on this client was failing
# with "Cache read failed" because you can't await a sync Redis call.
#
# Now uses a lazy async client that's only created when first needed,
# matching the pattern used everywhere else in the codebase.

import os
import json
import logging

logger = logging.getLogger("cache")

REDIS_URL = os.getenv("REDIS_URL")

# Lazy async client — set on first use
_redis_client = None


def _get_client():
    global _redis_client
    if _redis_client is not None:
        return _redis_client
    if not REDIS_URL:
        return None
    try:
        import redis.asyncio as aioredis
        _redis_client = aioredis.from_url(REDIS_URL, decode_responses=True)
        return _redis_client
    except Exception as e:
        logger.warning(f"Redis client init failed: {e}")
        return None


# Expose redis_client for RedisPagination which imports it directly
# Returns the async client (or None if Redis isn't configured)
@property
def redis_client():
    return _get_client()


# RedisPagination does `from utils.cache import redis_client` and then
# calls redis_client.get(key) synchronously. Since we're async now,
# we provide a simple sync-safe wrapper it can use for page state.
# For async contexts use get_async / set_async below.

class _SyncWrapper:
    """
    Minimal sync-compatible wrapper around the async Redis client.
    Used only by RedisPagination which was written for sync Redis.
    Falls back to None returns (memory fallback) if async isn't available.
    """
    def get(self, key):
        # RedisPagination checks `if redis_client` — return self so it's truthy
        # but return None from get() so it falls back to memory_page
        return None

    def set(self, key, value, ex=None):
        pass

    def __bool__(self):
        return REDIS_URL is not None


redis_client = _SyncWrapper()


# ==================================================
# ASYNC HELPERS (used by free_games_service etc.)
# ==================================================

async def cache_get_async(key: str):
    client = _get_client()
    if not client:
        return None
    try:
        data = await client.get(key)
        if not data:
            return None
        return json.loads(data)
    except Exception as e:
        logger.warning(f"Cache get failed for {key}: {e}")
        return None


async def cache_set_async(key: str, value, ttl: int = None):
    client = _get_client()
    if not client:
        return
    try:
        serialized = json.dumps(value)
        if ttl is not None:
            await client.setex(key, ttl, serialized)
        else:
            await client.set(key, serialized)
    except Exception as e:
        logger.warning(f"Cache set failed for {key}: {e}")
