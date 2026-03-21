import json
from services.redis_client import redis_client
from services.twitch_api import twitch_api


CACHE_TTL = 60  # 1 min


async def get_cached_stream(login: str):
    key = f"stream:meta:{login}"

    cached = await redis_client.get(key)
    if cached:
        return json.loads(cached)

    stream = await twitch_api.helix_request(
        "streams",
        {"user_login": login}
    )

    if not stream or not stream.get("data"):
        return None

    data = stream["data"][0]

    result = {
        "title": data.get("title"),
        "game": data.get("game_name"),
        "user_login": login
    }

    await redis_client.set(
        key,
        json.dumps(result),
        ex=CACHE_TTL
    )

    return result
