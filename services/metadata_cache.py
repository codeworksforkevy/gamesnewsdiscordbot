"""
metadata_cache.py
────────────────────────────────────────────────────────────────
Thin Redis cache for Twitch stream metadata.

Improvements over original:
- TTL is a named constant, not a magic number
- Added delete() for cache invalidation on stream.offline
- Added exists() for quick presence checks
"""

DEFAULT_TTL = 300   # 5 minutes — adjust per your stream poll frequency


class MetadataCache:

    def __init__(self, redis, ttl: int = DEFAULT_TTL):
        self.redis = redis
        self.ttl   = ttl

    def _key(self, bid: str) -> str:
        return f"stream:meta:{bid}"

    async def get(self, bid: str):
        return await self.redis.get(self._key(bid))

    async def set(self, bid: str, data) -> None:
        await self.redis.set(self._key(bid), data, ex=self.ttl)

    async def delete(self, bid: str) -> None:
        """Call on stream.offline to evict stale metadata immediately."""
        await self.redis.delete(self._key(bid))

    async def exists(self, bid: str) -> bool:
        return bool(await self.redis.exists(self._key(bid)))
