import os
import aiohttp

TWITCH_CLIENT_ID = os.getenv("TWITCH_CLIENT_ID")
TWITCH_CLIENT_SECRET = os.getenv("TWITCH_CLIENT_SECRET")

async def get_app_token():
    url = "https://id.twitch.tv/oauth2/token"
    params = {
        "client_id": TWITCH_CLIENT_ID,
        "client_secret": TWITCH_CLIENT_SECRET,
        "grant_type": "client_credentials"
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(url, params=params) as resp:
            data = await resp.json()
            return data.get("access_token")

async def resolve_user(login: str):
    token = await get_app_token()

    headers = {
        "Client-ID": TWITCH_CLIENT_ID,
        "Authorization": f"Bearer {token}"
    }

    url = f"https://api.twitch.tv/helix/users?login={login}"

    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers) as resp:
            data = await resp.json()
            if data.get("data"):
                return data["data"][0]
            return None
