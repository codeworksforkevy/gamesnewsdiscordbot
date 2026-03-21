class MetadataCache:

    def __init__(self, redis):
        self.redis = redis

    def _key(self, bid):
        return f"stream:{bid}"

    async def get(self, bid):
        return await self.redis.get(self._key(bid))

    async def set(self, bid, data):
        await self.redis.set(self._key(bid), data, ex=300)
