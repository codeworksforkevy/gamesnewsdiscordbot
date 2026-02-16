
import os
from utils.cache import cache_get, cache_set

TWITCH_CLIENT_ID = os.getenv("TWITCH_CLIENT_ID")
TWITCH_CLIENT_SECRET = os.getenv("TWITCH_CLIENT_SECRET")


# ---------------- TOKEN AUTO REFRESH ----------------

async def get_app_access_token(session):
    cache_key = "twitch_app_token"
    cached = cache_get(cache_key)
    if cached:
        return cached

    url = "https://id.twitch.tv/oauth2/token"

    payload = {
        "client_id": TWITCH_CLIENT_ID,
        "client_secret": TWITCH_CLIENT_SECRET,
        "grant_type": "client_credentials"
    }

    async with session.post(url, data=payload) as r:
        data = await r.json()

    token = data.get("access_token")
    expires = data.get("expires_in", 3600)

    if token:
        cache_set(cache_key, token, ttl=expires - 60)

    return token


# ---------------- OFFICIAL GLOBAL BADGES ----------------

async def fetch_official_global_badges(session):
    cache_key = "twitch_global_badges_official"
    cached = cache_get(cache_key)
    if cached:
        return cached

    token = await get_app_access_token(session)
    if not token:
        return {}

    headers = {
        "Client-ID": TWITCH_CLIENT_ID,
        "Authorization": f"Bearer {token}"
    }

    url = "https://api.twitch.tv/helix/chat/badges/global"

    async with session.get(url, headers=headers) as r:
        if r.status != 200:
            return {}
        data = await r.json()

    badges = []

    for badge in data.get("data", []):
        set_id = badge.get("set_id")
        versions = badge.get("versions", [])

        if not versions:
            continue

        image_url = versions[0].get("image_url_4x")

        badges.append({
            "set_id": set_id,
            "thumbnail": image_url
        })

    cache_set(cache_key, badges, ttl=3600)

    return badges
