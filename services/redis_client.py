import os
import aioredis

redis = aioredis.from_url(
    os.getenv("REDIS_URL"),
    decode_responses=True
)
