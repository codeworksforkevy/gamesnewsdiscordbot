import json
import logging
import time

logger = logging.getLogger("twitch-cache")

CACHE_TTL = 300  # seconds — raised from 60 to match MetadataCache default


async def get_cached_stream(login: str) -> dict | None:
    """
    Returns stream metadata for a live broadcaster, using Redis as a
    cache layer and falling back to the Twitch API on a miss.

    Fixed vs original:
    - Imported `init_twitch_api` which doesn't exist anywhere → ImportError.
      Now reads twitch_api from core.state_manager (set in main.py).
    - redis_client imported via the module-level proxy in redis_client.py.
    - Cache TTL raised from 60s to 300s to match MetadataCache default.
    - game_name key fixed (was "game", Twitch API field is "game_name").
    """
    from services.redis_client import redis_client

    key = f"stream:meta:{login}"

    # ── 1. Redis cache hit ──────────────────────────────────────────────
    cached = await redis_client.get(key)
    if cached:
        try:
            return json.loads(cached)
        except Exception as e:
            logger.warning(f"Cache parse error for {login}: {e}")

    # ── 2. Twitch API fetch ─────────────────────────────────────────────
    try:
        from core.state_manager import state
        api = state.get_bot().app_state.twitch_api
    except Exception as e:
        logger.error(f"Twitch API not available: {e}")
        return None

    if not api:
        logger.error("Twitch API not initialised on app_state")
        return None

    try:
        data = await api.helix_request("streams", {"user_login": login})
    except Exception as e:
        logger.error(f"Twitch API request failed for {login}: {e}")
        return None

    if not data or not data.get("data"):
        return None

    stream = data["data"][0]

    result = {
        "title":      stream.get("title"),
        "game_name":  stream.get("game_name"),   # fixed: was "game"
        "user_login": login,
        "viewer_count": stream.get("viewer_count"),
    }

    # ── 3. Cache store ──────────────────────────────────────────────────
    try:
        await redis_client.set(key, json.dumps(result), ttl=CACHE_TTL)
    except Exception as e:
        logger.warning(f"Redis set failed for {login}: {e}")

    return result
