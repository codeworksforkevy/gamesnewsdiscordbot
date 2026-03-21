import time
import hashlib


class CacheManager:
    def __init__(self, redis):
        self.redis = redis

    def _hash(self, key: str) -> str:
        return hashlib.sha256(key.encode()).hexdigest()

    async def get(self, key: str):
        if not self.redis:
            return None
        return await self.redis.get(self._hash(key))

    async def set(self, key: str, value, ttl: int = 600):
        if not self.redis:
            return
        await self.redis.setex(self._hash(key), ttl, value)

    async def is_duplicate(self, key: str, ttl: int = 1800):
        """
        Dedup mechanism:
        returns True if already seen
        """
        if not self.redis:
            return False

        hashed = self._hash(key)
        exists = await self.redis.exists(hashed)

        if exists:
            return True

        await self.redis.setex(hashed, ttl, str(time.time()))
        return False
