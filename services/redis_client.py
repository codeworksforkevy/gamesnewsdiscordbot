import redis.asyncio as redis
import os

REDIS_URL = os.getenv("REDIS_URL")

redis = redis.from_url(REDIS_URL, decode_responses=True)
