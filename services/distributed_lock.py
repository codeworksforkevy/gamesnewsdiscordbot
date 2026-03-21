class DistributedLock:

    def __init__(self, redis):
        self.redis = redis

    async def acquire(self, key, ttl=60):

        result = await self.redis.set(
            key,
            "1",
            nx=True,
            ex=ttl
        )

        return result is True

    async def release(self, key):

        await self.redis.delete(key)
