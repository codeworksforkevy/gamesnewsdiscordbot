import json
import logging

from services.epic import fetch_epic_free
from services.gog import fetch_gog_free
from services.diff_engine import diff_games
from core.event_bus import event_bus

logger = logging.getLogger("free-games")

CACHE_KEY = "free_games_cache"

# Railway fallback (non-persistent)
_memory_cache = []


# ==================================================
# RETRY HELPER
# ==================================================
async def retry_async(func, retries=3, delay=2):
    last_error = None

    for attempt in range(retries):
        try:
            return await func()
        except Exception as e:
            last_error = e
            await asyncio.sleep(delay * (2 ** attempt))

    raise last_error


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
# GET CACHE
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
# NORMALIZATION
# ==================================================
def normalize_games(games):
    normalized = []
    seen = set()

    for game in games:
        key = (
            game.get("title")
            or game.get("name")
            or game.get("id")
        )

        if not key or key in seen:
            continue

        seen.add(key)
        normalized.append(game)

    return normalized


# ==================================================
# FETCH + PROCESS PIPELINE (EVENT-DRIVEN)
# ==================================================
async def update_free_games_cache(session, redis=None):

    global _memory_cache

    try:
        # -------------------------
        # FETCH (ISOLATED + RETRY)
        # -------------------------
        async def fetch_epic():
            return await fetch_epic_free(session)

        async def fetch_gog():
            return await fetch_gog_free(session)

        try:
            epic = await retry_async(fetch_epic)
        except Exception as e:
            logger.warning(
                "Epic fetch failed",
                extra={"extra_data": {"error": str(e)}}
            )
            epic = []

        try:
            gog = await retry_async(fetch_gog)
        except Exception as e:
            logger.warning(
                "GOG fetch failed",
                extra={"extra_data": {"error": str(e)}}
            )
            gog = []

        # -------------------------
        # MERGE + NORMALIZE
        # -------------------------
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
        # EVENT EMIT (CRITICAL)
        # -------------------------
        await event_bus.emit("free_games_fetched", new_only)

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
