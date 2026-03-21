import os
import time
import asyncio
import logging
import aiohttp

logger = logging.getLogger("twitch-api")

TOKEN_URL = "https://id.twitch.tv/oauth2/token"
HELIX_BASE = "https://api.twitch.tv/helix"


class TwitchAPI:

    def __init__(self, session: aiohttp.ClientSession):

        self.session = session

        self.client_id = os.getenv("TWITCH_CLIENT_ID")
        self.client_secret = os.getenv("TWITCH_CLIENT_SECRET")

        if not self.client_id or not self.client_secret:
            raise RuntimeError("Twitch credentials missing")

        self._app_token = None
        self._expiry = 0
        self._token_lock = asyncio.Lock()

    async def get_app_token(self):

        async with self._token_lock:

            now = time.time()

            if self._app_token and now < self._expiry:
                return self._app_token

            payload = {
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "grant_type": "client_credentials"
            }

            async with self.session.post(TOKEN_URL, data=payload) as resp:

                if resp.status != 200:
                    text = await resp.text()
                    logger.error("Token request failed: %s", text)
                    return None

                data = await resp.json()

                self._app_token = data["access_token"]
                expires_in = data.get("expires_in", 3600)

                self._expiry = now + expires_in - 60

                logger.info("Twitch token refreshed")

                return self._app_token

    async def helix_request(self, endpoint, params=None):

        token = await self.get_app_token()
        if not token:
            return None

        headers = {
            "Client-ID": self.client_id,
            "Authorization": f"Bearer {token}"
        }

        url = f"{HELIX_BASE}/{endpoint}"

        async with self.session.get(url, headers=headers, params=params) as resp:

            if resp.status == 401:
                self._app_token = None
                return await self.helix_request(endpoint, params)

            if resp.status != 200:
                logger.error("Helix error: %s", await resp.text())
                return None

            return await resp.json()


# ==================================================
# GLOBAL INSTANCE (FIX HERE)
# ==================================================

twitch_api: TwitchAPI | None = None


async def init_twitch_api():
    global twitch_api

    if twitch_api is not None:
        return twitch_api

    import aiohttp

    session = aiohttp.ClientSession()

    twitch_api = TwitchAPI(session)

    return twitch_api
