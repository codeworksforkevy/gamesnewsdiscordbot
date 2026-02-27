import os
import redis
import json
import logging

logger = logging.getLogger("cache")

# ---------------------------------------------------
# REDIS CONNECTION
# ---------------------------------------------------

REDIS_URL = os.getenv("REDIS_URL")

redis_client = None

if REDIS_URL:
    try:
        redis_client = redis.from_url(
            REDIS_URL,
            decode_responses=True
        )

        # Health check
        redis_client.ping()
        logger.info("Redis connected successfully.")

    except Exception as e:
        logger.exception("Redis connection failed: %s", e)
        redis_client = None
else:
    logger.info("REDIS_URL not set. Cache disabled.")


# ---------------------------------------------------
# CACHE GET
# ---------------------------------------------------

def cache_get(key):
    if not redis_client:
        return None

    try:
        data = redis_client.get(key)

        if not data:
            return None

        return json.loads(data)

    except Exception as e:
        logger.warning("Cache get failed for key %s: %s", key, e)
        return None


# ---------------------------------------------------
# CACHE SET (TTL SUPPORT)
# ---------------------------------------------------

def cache_set(key, value, ttl=None):
    if not redis_client:
        return

    try:
        serialized = json.dumps(value)

        if ttl is not None:
            redis_client.setex(key, ttl, serialized)
        else:
            redis_client.set(key, serialized)

    except Exception as e:
        logger.warning("Cache set failed for key %s: %s", key, e)
