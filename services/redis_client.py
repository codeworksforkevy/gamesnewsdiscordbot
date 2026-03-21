import os
import redis.asyncio as redis

REDIS_URL = os.getenv("REDIS_URL")

if not REDIS_URL:
    raise ValueError("REDIS_URL is not set in environment variables")

redis = redis.from_url(REDIS_URL, decode_responses=True)
