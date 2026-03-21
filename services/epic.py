import json
import logging
from typing import List, Dict

from services.epic import fetch_epic_free
from services.gog import fetch_gog_free
from services.diff_engine import diff_games
from services.notifier import notify_discord

logger = logging.getLogger("free-games")

CACHE_KEY = "free_games_cache"
_memory_cache: List[Dict] = []


# ==================================================
# CACHE INIT
# ==================================================
async def init_cache(redis=None):
    if not redis:
        return

    try:
        if not await redis.exists(CACHE_KEY):
            await redis.set(CACHE_KEY, json.dumps([]))
    except Exception as e:
        logger.warning(f"Cache init failed: {e}")


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
            cached = cached.decode()

        data = json.loads(cached)

        if not isinstance(data, list):
            return _memory_cache

        _memory_cache = data
        return data

    except Exception as e:
        logger.warning(f"Cache read failed: {e}")
        return _memory_cache


# ==================================================
# NORMALIZATION (UX IMPROVEMENT)
# ==================================================
def _normalize_game(game: Dict) -> Dict:
    """
    UX layer:
    - ensures consistency
    - adds fallback fields
    """

    return {
        "id": game.get("id"),
        "title": game.get("title", "Unknown"),
        "platform": game.get("platform"),
        "url": game.get("url"),
        "thumbnail": game.get("thumbnail"),
        "start_date": game.get("start_date"),
        "end_date": game.get("end_date"),

        # UX enrichments
        "description": f"Free on {game.get('platform')}",
        "tags": ["free", game.get("platform", "").lower()],
    }


# ==================================================
# UPDATE PIPELINE (CORE)
# ==================================================
async def update_free_games_cache(session, bot=None, redis=None):

    global _memory_cache

    try:
        # -------------------------
        # FETCH (ISOLATED)
        # -------------------------
        epic = await fetch_epic_free(session)
        gog = await fetch_gog_free(session)

        new_games = epic + gog

        # normalize
        new_games = [_normalize_game(g) for g in new_games]

        # -------------------------
        # LOAD OLD CACHE
        # -------------------------
        old_games = await get_cached_free_games(redis)

        # -------------------------
        # DIFF
        # -------------------------
        new_only = diff_games(old_games, new_games)

        if not new_only:
            logger.info("No new games")
            return

        logger.info(f"New games: {len(new_only)}")

        # -------------------------
        # NOTIFY
        # -------------------------
        if bot:
            try:
                await notify_discord(bot, new_only)
            except Exception as e:
                logger.warning(f"Notify failed: {e}")

        # -------------------------
        # UPDATE CACHE
        # -------------------------
        _memory_cache = new_games

        if redis:
            await redis.set(CACHE_KEY, json.dumps(new_games))

    except Exception as e:
        logger.error(f"Pipeline failed: {e}")
