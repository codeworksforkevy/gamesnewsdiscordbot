# services/free_games_service.py

import os
import json
import logging
import asyncio

from services.epic import fetch_epic_free
from services.gog import fetch_gog_free
from services.humble import fetch_humble_free
from services.luna import fetch_luna_free
from services.steam import fetch_steam_free

from services.redis_client import RedisClient
from services.diff_engine import get_new_items
from services.notifier import notify_new_games

logger = logging.getLogger("free-games-service")

REDIS_URL = os.getenv("REDIS_URL")

_redis_client: RedisClient | None = None
_memory_cache = []
_cache_lock = asyncio.Lock()

# simple circuit breaker state
_fail_counts = {}


# ==================================================
# REDIS INIT
# ==================================================

async def init_cache():
    global _redis_client

    if not REDIS_URL:
        logger.info("REDIS_URL not set. Cache disabled.")
        return

    try:
        import redis.asyncio as redis

        raw = redis.from_url(REDIS_URL)
        _redis_client = RedisClient(raw)

        logger.info("Redis cache enabled.")

    except Exception as e:
        logger.warning(
            "Redis init failed",
            extra={"extra_data": {"error": str(e)}}
        )
        _redis_client = None


# ==================================================
# SAFE FETCH (ISOLATION + CIRCUIT BREAKER)
# ==================================================

async def safe_fetch(name, coro):

    # circuit breaker (very simple)
    if _fail_counts.get(name, 0) >= 5:
        logger.warning(f"{name} circuit open - skipping fetch")
        return []

    try:
        result = await coro
        _fail_counts[name] = 0
        return result or []

    except Exception as e:
        _fail_counts[name] = _fail_counts.get(name, 0) + 1

        logger.warning(
            f"{name} fetch failed",
            extra={"extra_data": {"error": str(e)}}
        )

        return []


# ==================================================
# UPDATE CACHE
# ==================================================

async def update_free_games_cache(session):

    global _memory_cache

    try:
        epic, gog, humble, luna, steam = await asyncio.gather(
            safe_fetch("Epic", fetch_epic_free(session)),
            safe_fetch("GOG", fetch_gog_free(session)),
            safe_fetch("Humble", fetch_humble_free(session)),
            safe_fetch("Luna", fetch_luna_free(session)),
            safe_fetch("Steam", fetch_steam_free(session)),
        )

        combined = epic + gog + humble + luna + steam

        # Deduplicate
        unique = {
            f"{o.get('platform')}-{o.get('title')}": o
            for o in combined
            if o.get("title")
        }.values()

        combined = list(unique)

    except Exception as e:
        logger.exception(
            "Free games update failed (fatal)",
            extra={"extra_data": {"error": str(e)}}
        )
        return

    # -------------------------
    # STORE REDIS
    # -------------------------
    if _redis_client:
        try:
            await _redis_client.set_json(
                "free_games_cache",
                combined,
                ttl=1800
            )
        except Exception:
            logger.warning("Redis write failed")

    # -------------------------
    # STORE MEMORY
    # -------------------------
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
    if _redis_client:
        try:
            data = await _redis_client.get_json("free_games_cache")
            if data:
                return data
        except Exception:
            logger.warning("Redis read failed")

    # fallback memory
    async with _cache_lock:
        return list(_memory_cache)
