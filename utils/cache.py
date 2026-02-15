import json
import redis
from config import REDIS_URL, CACHE_TTL

redis_client = redis.from_url(REDIS_URL) if REDIS_URL else None

def cache_set(key, value):
    if redis_client:
        redis_client.setex(key, CACHE_TTL, json.dumps(value))

def cache_get(key):
    if redis_client:
        data = redis_client.get(key)
        if data:
            return json.loads(data)
    return None
