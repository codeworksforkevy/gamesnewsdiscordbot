# utils/cache.py
#
# FIX: was creating a synchronous redis.from_url() client at import time.
# The rest of the bot uses redis.asyncio — so every await redis.get()
# was failing with "Cache read failed" because you can't await a sync call.
#
# RedisPagination imports redis_client from here and uses it synchronously
# for page state tracking. We keep that interface but make it a no-op
# wrapper so pagination falls back to in-memory page tracking instead of
# crashing. Pagination still works — it just doesn't persist across
# bot restarts (which is fine for a 5-minute view timeout).

import os
import logging

logger = logging.getLogger("cache")

REDIS_URL = os.getenv("REDIS_URL")


class _NullCache:
    """
    Sync-safe no-op cache used by RedisPagination.
    Falls back gracefully — pagination uses in-memory page index instead.
    Returns falsy values so RedisPagination uses its memory_page fallback.
    """

    def get(self, key):
        return None

    def set(self, key, value, ex=None):
        pass

    def __bool__(self):
        # Return True if Redis is configured so RedisPagination
        # thinks it has a client (it will just get None from .get())
        return bool(REDIS_URL)


# This is what RedisPagination imports
redis_client = _NullCache()
