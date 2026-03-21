import json
import logging

from services.epic import fetch_epic_free
from services.gog import fetch_gog_free
from services.diff_engine import diff_games
from services.notifier import notify_discord

logger = logging.getLogger("free-games")

CACHE_KEY = "free_games_cache"

# Railway fallback (non-persistent)
_memory_cache = []


# ==================================================
# INIT CACHE
# ==================================================

async def init_cache(redis=None):
    if not redis:
        return

    try:
        exists = await redis.exists(CACHE_KEY)

        if not exists:
            await redis.set(CACHE_KEY, json.dumps([]))

    except Exception as e:
        logger.warning(
            "Cache init failed",
            extra={"extra_data": {"error": str(e)}}
        )


# ==================================================
# GET CACHE (SAFE + FALLBACK)
# ==================================================

async def get_cached_free_games(redis=None):
    global _memory_cache

    if not redis:
        return _memory_cache

    try:
        cached = await redis.get(CACHE_KEY)

        if not cached:
            return _memory_cache

        if isinstance(cached, bytes):
            cached = cached.decode("utf-8")

        data = json.loads(cached)

        if not isinstance(data, list):
            return _memory_cache

        _memory_cache = data
        return data

    except Exception as e:
        logger.warning(
            "Cache read failed",
            extra={"extra_data": {"error": str(e)}}
        )
        return _memory_cache


# ==================================================
# NORMALIZATION (OPTIONAL BUT STRONG)
# ==================================================

def normalize_games(games):
    """
    Prevent duplicate spam by normalizing game identity
    """
    normalized = []

    seen = set()

    for game in games:
        # fallback identity strategy
        key = (
            game.get("title") or
            game.get("name") or
            game.get("id")
        )

        if not key:
            continue

        if key in seen:
            continue

        seen.add(key)
        normalized.append(game)

    return normalized


# ==================================================
# UPDATE CACHE + DIFF + NOTIFY
# ==================================================

async def update_free_games_cache(session, bot=None, redis=None):

    global _memory_cache

    try:
        # -------------------------
        # FETCH (ISOLATED)
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

        # Merge + normalize
        new_games = normalize_games(epic + gog)

        # -------------------------
        # LOAD CACHE
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
        # NOTIFY (SAFE)
        # -------------------------
        if bot:
            try:
                await notify_discord(bot, new_only)
            except Exception as e:
                logger.exception(
                    "Notify failed",
                    extra={"extra_data": {"error": str(e)}}
                )

        # -------------------------
        # CACHE UPDATE (SAFE)
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
        logger.exception(
            "Free games update failed",
            extra={"extra_data": {"error": str(e)}}
        )
