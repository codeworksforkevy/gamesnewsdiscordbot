import aiohttp
import os
import time
import asyncio

CLIENT_ID = os.getenv("TWITCH_CLIENT_ID")
CLIENT_SECRET = os.getenv("TWITCH_CLIENT_SECRET")

TWITCH_API = "https://api.twitch.tv/helix/eventsub/subscriptions"

# ==================================================
# TOKEN CACHE (IMPORTANT)
# ==================================================

_token = None
_token_expiry = 0


async def get_app_token():

    global _token, _token_expiry

    now = time.time()

    if _token and now < _token_expiry:
        return _token

    url = "https://id.twitch.tv/oauth2/token"

    params = {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "grant_type": "client_credentials"
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(url, params=params) as resp:
            data = await resp.json()

    _token = data["access_token"]
    _token_expiry = now + data.get("expires_in", 3600) - 60

    return _token


# ==================================================
# SUBSCRIBE STREAM ONLINE
# ==================================================

async def subscribe_stream_online(user_id: str, callback_url: str):

    token = await get_app_token()

    headers = {
        "Client-ID": CLIENT_ID,
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    body = {
        "type": "stream.online",
        "version": "1",
        "condition": {
            "broadcaster_user_id": user_id
        },
        "transport": {
            "method": "webhook",
            "callback": callback_url,
            "secret": os.getenv("TWITCH_WEBHOOK_SECRET")
        }
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(TWITCH_API, headers=headers, json=body) as resp:

            try:
                data = await resp.json()
            except Exception:
                data = {"error": "invalid response"}

            return {
                "status": resp.status,
                "response": data
            }


# ==================================================
# OPTIONAL: UNSUBSCRIBE (FUTURE USE)
# ==================================================

async def unsubscribe(subscription_id: str):

    token = await get_app_token()

    headers = {
        "Client-ID": CLIENT_ID,
        "Authorization": f"Bearer {token}"
    }

    async with aiohttp.ClientSession() as session:
        async with session.delete(
            f"{TWITCH_API}?id={subscription_id}",
            headers=headers
        ) as resp:
            return resp.status
