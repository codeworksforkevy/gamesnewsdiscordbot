# services/redis_client.py

import json
import logging

logger = logging.getLogger("redis-client")


class RedisClient:
    def __init__(self, redis):
        self.redis = redis

    # -------------------------
    # RAW
    # -------------------------
    async def get(self, key):
        if not self.redis:
            return None
        try:
            return await self.redis.get(key)
        except Exception as e:
            logger.warning("Redis GET failed", extra={"error": str(e)})
            return None

    async def set(self, key, value, ttl=300):
        if not self.redis:
            return
        try:
            await self.redis.set(key, value, ex=ttl)
        except Exception as e:
            logger.warning("Redis SET failed", extra={"error": str(e)})

    # -------------------------
    # JSON HELPERS
    # -------------------------
    async def get_json(self, key):
        if not self.redis:
            return None

        try:
            data = await self.redis.get(key)
            if not data:
                return None

            if isinstance(data, bytes):
                data = data.decode("utf-8")

            return json.loads(data)

        except Exception as e:
            logger.warning("Redis GET_JSON failed", extra={"error": str(e)})
            return None

    async def set_json(self, key, value, ttl=300):
        if not self.redis:
            return

        try:
            payload = json.dumps(value)
            await self.redis.set(key, payload, ex=ttl)

        except Exception as e:
            logger.warning("Redis SET_JSON failed", extra={"error": str(e)})
