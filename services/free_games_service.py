import os
import json
import logging
import asyncio

from services.epic import fetch_epic_free
from services.gog import fetch_gog_free
from services.humble import fetch_humble_free
from services.luna import fetch_luna_free
from services.steam import fetch_steam_free

logger = logging.getLogger("free-games-service")

REDIS_URL = os.getenv("REDIS_URL")

_redis = None
_memory_cache = []
_cache_lock = asyncio.Lock()


# ==================================================
# REDIS INIT (OPTIONAL)
# ==================================================

async def init_cache():
    global _redis

    if not REDIS_URL:
        logger.info("REDIS_URL not set. Cache disabled.")
        return

    try:
        import redis.asyncio as redis
        _redis = redis.from_url(REDIS_URL)
        logger.info("Redis cache enabled.")
    except Exception as e:
        logger.warning(
            "Redis init failed",
            extra={"extra_data": {"error": str(e)}}
        )
        _redis = None


# ==================================================
# UPDATE CACHE
# ==================================================

async def update_free_games_cache(session):

    global _memory_cache

    try:
        epic = await fetch_epic_free(session)
        gog = await fetch_gog_free(session)
        humble = await fetch_humble_free(session)
        luna = await fetch_luna_free(session)
        steam = await fetch_steam_free(session)

        combined = epic + gog + humble + luna + steam

        # Deduplicate by (platform + title)
        unique = {
            f"{o['platform']}-{o['title']}": o
            for o in combined
        }.values()

        combined = list(unique)

    except Exception as e:
        logger.exception(
            "Free games update failed",
            extra={"extra_data": {"error": str(e)}}
        )
        return

    # Store
    if _redis:
        try:
            await _redis.set(
                "free_games_cache",
                json.dumps(combined),
                ex=1800
            )
        except Exception:
            logger.warning("Redis write failed")

    async with _cache_lock:
        _memory_cache = combined

    logger.info(
        "Free games cache updated",
        extra={"extra_data": {"count": len(combined)}}
    )


# ==================================================
# GET CACHE
# ==================================================

async def get_cached_free_games():

    # Redis first
    if _redis:
        try:
            data = await _redis.get("free_games_cache")
            if data:
                return json.loads(data)
        except Exception:
            logger.warning("Redis read failed")

    # Fallback memory
    async with _cache_lock:
        return list(_memory_cache)
