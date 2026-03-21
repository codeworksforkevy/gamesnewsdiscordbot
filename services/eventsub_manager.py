import aiohttp
import os

CLIENT_ID = os.getenv("TWITCH_CLIENT_ID")
CLIENT_SECRET = os.getenv("TWITCH_CLIENT_SECRET")

TWITCH_API = "https://api.twitch.tv/helix/eventsub/subscriptions"

async def get_app_token():
    url = "https://id.twitch.tv/oauth2/token"

    params = {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "grant_type": "client_credentials"
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(url, params=params) as resp:
            data = await resp.json()

    return data["access_token"]
