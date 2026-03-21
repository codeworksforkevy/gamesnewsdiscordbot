import json
from services.redis_client import redis
from services.twitch_api import get_stream_data

CACHE_TTL = 60  # 60 saniye cache (optimize)

async def get_cached_stream(user_login: str):

    key = f"stream:{user_login}"

    cached = await redis.get(key)

    if cached:
        return json.loads(cached)

    # cache miss → API call
    data = await get_stream_data(user_login)

    if data:
        await redis.set(key, json.dumps(data), ex=CACHE_TTL)

    return data
