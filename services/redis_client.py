"""
services/redis_client.py
────────────────────────────────────────────────────────────────
Thin async wrapper around aioredis / redis-py async.

Improvements over original:
- Added delete() and exists() — both needed by event_router and metadata_cache
- TTL parameter renamed to `ttl` everywhere for consistency
- Error logs now include the key so you can trace failures instantly
- Graceful no-op when redis is None (offline / test mode) on all methods
- get() returns decoded str, not raw bytes — callers don't need to .decode()
"""

import json
import logging
from typing import Any, Optional

logger = logging.getLogger("redis-client")


class RedisClient:

    def __init__(self, redis):
        """
        redis: an async Redis connection (aioredis / redis.asyncio).
               Pass None to run in no-op mode (useful for local dev / tests).
        """
        self.redis = redis

    # ──────────────────────────────────────────────────────────
    # RAW STRING OPS
    # ──────────────────────────────────────────────────────────

    async def get(self, key: str) -> Optional[str]:
        if not self.redis:
            return None
        try:
            value = await self.redis.get(key)
            if value is None:
                return None
            return value.decode("utf-8") if isinstance(value, bytes) else value
        except Exception as e:
            logger.warning(
                "Redis GET failed",
                extra={"extra_data": {"key": key, "error": str(e)}},
            )
            return None

    async def set(self, key: str, value: Any, ttl: int = 300) -> bool:
        """Returns True on success, False on error or no-op."""
        if not self.redis:
            return False
        try:
            await self.redis.set(key, value, ex=ttl)
            return True
        except Exception as e:
            logger.warning(
                "Redis SET failed",
                extra={"extra_data": {"key": key, "error": str(e)}},
            )
            return False

    async def delete(self, *keys: str) -> int:
        """
        Deletes one or more keys.
        Returns the number of keys actually deleted.
        """
        if not self.redis or not keys:
            return 0
        try:
            return await self.redis.delete(*keys)
        except Exception as e:
            logger.warning(
                "Redis DELETE failed",
                extra={"extra_data": {"keys": list(keys), "error": str(e)}},
            )
            return 0

    async def exists(self, key: str) -> bool:
        """Returns True if the key is present in Redis."""
        if not self.redis:
            return False
        try:
            return bool(await self.redis.exists(key))
        except Exception as e:
            logger.warning(
                "Redis EXISTS failed",
                extra={"extra_data": {"key": key, "error": str(e)}},
            )
            return False

    async def ttl(self, key: str) -> int:
        """
        Returns seconds remaining on the key's TTL.
        -1 means no TTL, -2 means key doesn't exist.
        """
        if not self.redis:
            return -2
        try:
            return await self.redis.ttl(key)
        except Exception as e:
            logger.warning(
                "Redis TTL failed",
                extra={"extra_data": {"key": key, "error": str(e)}},
            )
            return -2

    # ──────────────────────────────────────────────────────────
    # JSON HELPERS
    # ──────────────────────────────────────────────────────────

    async def get_json(self, key: str) -> Optional[Any]:
        if not self.redis:
            return None
        try:
            raw = await self.redis.get(key)
            if not raw:
                return None
            text = raw.decode("utf-8") if isinstance(raw, bytes) else raw
            return json.loads(text)
        except Exception as e:
            logger.warning(
                "Redis GET_JSON failed",
                extra={"extra_data": {"key": key, "error": str(e)}},
            )
            return None

    async def set_json(self, key: str, value: Any, ttl: int = 300) -> bool:
        """Returns True on success."""
        if not self.redis:
            return False
        try:
            payload = json.dumps(value, ensure_ascii=False)
            await self.redis.set(key, payload, ex=ttl)
            return True
        except Exception as e:
            logger.warning(
                "Redis SET_JSON failed",
                extra={"extra_data": {"key": key, "error": str(e)}},
            )
            return False

    # ──────────────────────────────────────────────────────────
    # HEALTHCHECK
    # ──────────────────────────────────────────────────────────

    async def ping(self) -> bool:
        """Returns True if Redis is reachable."""
        if not self.redis:
            return False
        try:
            return await self.redis.ping()
        except Exception:
            return False
