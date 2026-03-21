import os
import time
import asyncio
import logging
import aiohttp

logger = logging.getLogger("twitch-api")

TOKEN_URL = "https://id.twitch.tv/oauth2/token"
HELIX = "https://api.twitch.tv/helix"


class TwitchAPI:

    def __init__(self, session):
        self.session = session

        self.client_id = os.getenv("TWITCH_CLIENT_ID")
        self.client_secret = os.getenv("TWITCH_CLIENT_SECRET")

        self._token = None
        self._expiry = 0
        self._lock = asyncio.Lock()

    async def get_token(self):

        async with self._lock:

            now = time.time()

            if self._token and now < self._expiry:
                return self._token

            async with self.session.post(
                TOKEN_URL,
                data={
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "grant_type": "client_credentials"
                }
            ) as resp:

                data = await resp.json()

                self._token = data["access_token"]
                self._expiry = now + data.get("expires_in", 3600) - 60

                return self._token

    async def request(self, endpoint, params=None):

        token = await self.get_token()

        headers = {
            "Client-ID": self.client_id,
            "Authorization": f"Bearer {token}"
        }

        async with self.session.get(
            f"{HELIX}/{endpoint}",
            headers=headers,
            params=params
        ) as resp:

            if resp.status != 200:
                return None

            return await resp.json()

    # ==================================================
    # 🔥 STREAM METADATA
    # ==================================================

    async def get_stream_metadata(self, broadcaster_id):

        data = await self.request(
            "streams",
            {"user_id": broadcaster_id}
        )

        if not data or not data.get("data"):
            return None

        stream = data["data"][0]

        return {
            "title": stream.get("title"),
            "game": stream.get("game_name")
        }
