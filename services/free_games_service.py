# services/free_games_service.py

import json
import logging

from services.epic import fetch_epic_free
from services.gog import fetch_gog_free
from services.diff_engine import diff_games
from services.notifier import notify_discord

logger = logging.getLogger("free-games")


CACHE_KEY = "free_games_cache"


# ==================================================
# INIT CACHE
# ==================================================

async def init_cache(redis=None):
    if not redis:
        return

    if not await redis.exists(CACHE_KEY):
        await redis.set(CACHE_KEY, json.dumps([]))


# ==================================================
# UPDATE CACHE + DIFF
# ==================================================

async def update_free_games_cache(session, bot=None, redis=None):

    try:
        epic = await fetch_epic_free(session)
        gog = await fetch_gog_free(session)

        new_games = epic + gog

        # -------------------------
        # LOAD OLD CACHE
        # -------------------------
        old_games = []

        if redis:
            cached = await redis.get(CACHE_KEY)
            if cached:
                old_games = json.loads(cached)

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
            await notify_discord(bot, new_only)

        # -------------------------
        # UPDATE CACHE
        # -------------------------
        if redis:
            await redis.set(CACHE_KEY, json.dumps(new_games))

    except Exception as e:
        logger.error(
            "Free games update failed",
            extra={"extra_data": {"error": str(e)}}
        )
