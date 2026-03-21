# services/free_games_service.py

import json
import logging

from services.epic import fetch_epic_free
from services.gog import fetch_gog_free
from services.diff_engine import diff_games
from services.notifier import notify_discord

logger = logging.getLogger("free-games")


CACHE_KEY = "free_games_cache"

# fallback in-memory cache (Railway restart-safe değil ama fallback olarak)
_memory_cache = []


# ==================================================
# INIT CACHE
# ==================================================

async def init_cache(redis=None):
    """
    Initialize cache safely
    """

    if not redis:
        return

    try:
        if not await redis.exists(CACHE_KEY):
            await redis.set(CACHE_KEY, json.dumps([]))

    except Exception as e:
        logger.warning(
            "Cache init failed",
            extra={"extra_data": {"error": str(e)}}
        )


# ==================================================
# GET CACHE (FIXED MISSING FUNCTION)
# ==================================================

async def get_cached_free_games(redis=None):
    """
    Returns cached games safely
    """

    global _memory_cache

    if not redis:
        return _memory_cache

    try:
        cached = await redis.get(CACHE_KEY)

        if not cached:
            return _memory_cache

        # Redis returns bytes sometimes
        if isinstance(cached, bytes):
            cached = cached.decode("utf-8")

        data = json.loads(cached)

        if not isinstance(data, list):
            return _memory_cache

        _memory_cache = data
        return data

    except Exception as e:
        logger.warning(
            "Failed to read cache",
            extra={"extra_data": {"error": str(e)}}
        )

        return _memory_cache


# ==================================================
# UPDATE CACHE + DIFF + NOTIFY
# ==================================================

async def update_free_games_cache(session, bot=None, redis=None):

    global _memory_cache

    try:
        # -------------------------
        # FETCH SOURCES (ISOLATED)
        # -------------------------
        epic = []
        gog = []

        try:
            epic = await fetch_epic_free(session)
        except Exception as e:
            logger.warning(
                "Epic fetch failed",
                extra={"extra_data": {"error": str(e)}}
            )

        try:
            gog = await fetch_gog_free(session)
        except Exception as e:
            logger.warning(
                "GOG fetch failed",
                extra={"extra_data": {"error": str(e)}}
            )

        new_games = epic + gog

        # -------------------------
        # LOAD OLD CACHE
        # -------------------------
        old_games = await get_cached_free_games(redis)

        # -------------------------
        # DIFF
        # -------------------------
        new_only = diff_games(old_games, new_games)

        if not new_only:
            logger.info("No new games found")
            return

        logger.info(
            "New games detected",
            extra={"extra_data": {"count": len(new_only)}}
        )

        # -------------------------
        # NOTIFY
        # -------------------------
        if bot:
            try:
                await notify_discord(bot, new_only)
            except Exception as e:
                logger.warning(
                    "Notify failed",
                    extra={"extra_data": {"error": str(e)}}
                )

        # -------------------------
        # UPDATE CACHE
        # -------------------------
        try:
            _memory_cache = new_games

            if redis:
                await redis.set(CACHE_KEY, json.dumps(new_games))

        except Exception as e:
            logger.warning(
                "Cache update failed",
                extra={"extra_data": {"error": str(e)}}
            )

    except Exception as e:
        logger.error(
            "Free games update failed",
            extra={"extra_data": {"error": str(e)}}
        )
