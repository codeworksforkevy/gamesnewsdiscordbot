import os
import redis
import json
import time

# ---------------------------------------------------
# REDIS CONNECTION
# ---------------------------------------------------

REDIS_URL = os.getenv("REDIS_URL")

redis_client = None

if REDIS_URL:
    redis_client = redis.from_url(REDIS_URL, decode_responses=True)


# ---------------------------------------------------
# CACHE GET
# ---------------------------------------------------

def cache_get(key):
    if not redis_client:
        return None

    data = redis_client.get(key)
    if not data:
        return None

    try:
        return json.loads(data)
    except Exception:
        return None


# ---------------------------------------------------
# CACHE SET (TTL SUPPORT)
# ---------------------------------------------------

def cache_set(key, value, ttl=None):
    if not redis_client:
        return

    try:
        serialized = json.dumps(value)
        if ttl:
            redis_client.setex(key, ttl, serialized)
        else:
            redis_client.set(key, serialized)
    except Exception:
        pass
