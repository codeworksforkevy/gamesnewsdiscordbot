class RedisClient:

    def __init__(self, redis):
        self.redis = redis

    async def get(self, key):
        return await self.redis.get(key)

    async def set(self, key, value, ttl=300):
        await self.redis.set(key, value, ex=ttl)
