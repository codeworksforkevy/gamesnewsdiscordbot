import json
import logging

from services.redis_client import redis_client
from services.twitch_api import init_twitch_api


logger = logging.getLogger("twitch-cache")

CACHE_TTL = 60  # seconds


# ==================================================
# GET STREAM (CACHED)
# ==================================================

async def get_cached_stream(login: str):

    key = f"stream:meta:{login}"

    # ------------------------------
    # 1. Redis Cache Hit
    # ------------------------------
    cached = await redis_client.get(key)

    if cached:
        try:
            return json.loads(cached)
        except Exception as e:
            logger.warning(f"Cache parse error: {e}")

    # ------------------------------
    # 2. Initialize Twitch API
    # ------------------------------
    api = await init_twitch_api()

    if not api:
        logger.error("Twitch API not initialized")
        return None

    # ------------------------------
    # 3. Fetch from Twitch
    # ------------------------------
    data = await api.helix_request(
        "streams",
        {"user_login": login}
    )

    if not data or not data.get("data"):
        return None

    stream = data["data"][0]

    result = {
        "title": stream.get("title"),
        "game": stream.get("game_name"),
        "user_login": login
    }

    # ------------------------------
    # 4. Cache Store
    # ------------------------------
    try:
        await redis_client.set(
            key,
            json.dumps(result),
            ex=CACHE_TTL
        )
    except Exception as e:
        logger.warning(f"Redis set failed: {e}")

    return result
