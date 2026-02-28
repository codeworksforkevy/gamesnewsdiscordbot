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

    # ==================================================
    # TOKEN MANAGEMENT (CONCURRENCY SAFE)
    # ==================================================

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

                # expire slightly early
                self._expiry = now + expires_in - 60

                logger.info("Twitch app token refreshed.")

                return self._app_token

    # ==================================================
    # GENERIC HELIX REQUEST (SAFE + RETRY)
    # ==================================================

    async def helix_request(self, endpoint, params=None, retry=True):

        token = await self.get_app_token()
        if not token:
            return None

        headers = {
            "Client-ID": self.client_id,
            "Authorization": f"Bearer {token}"
        }

        url = f"{HELIX_BASE}/{endpoint}"

        async with self.session.get(
            url,
            headers=headers,
            params=params
        ) as resp:

            # Auto refresh on 401
            if resp.status == 401 and retry:
                logger.warning("Token expired. Refreshing.")
                self._app_token = None
                await self.get_app_token()
                return await self.helix_request(endpoint, params, retry=False)

            # Rate limit handling
            if resp.status == 429:
                retry_after = int(resp.headers.get("Retry-After", 1))
                logger.warning(
                    "Rate limited. Sleeping %s seconds.",
                    retry_after
                )
                await asyncio.sleep(retry_after)
                return await self.helix_request(endpoint, params, retry=False)

            if resp.status != 200:
                text = await resp.text()
                logger.error(
                    "Helix request failed (%s): %s",
                    resp.status,
                    text
                )
                return None

            return await resp.json()

    # ==================================================
    # USER RESOLUTION
    # ==================================================

    async def resolve_user(self, login: str):
        data = await self.helix_request(
            "users",
            {"login": login}
        )

        if data and data.get("data"):
            return data["data"][0]

        return None

    async def get_user_by_id(self, user_id: str):
        data = await self.helix_request(
            "users",
            {"id": user_id}
        )

        if data and data.get("data"):
            return data["data"][0]

        return None

    # ==================================================
    # STREAM CHECK (SINGLE)
    # ==================================================

    async def check_stream_live(self, user_id: str):

        data = await self.helix_request(
            "streams",
            {"user_id": user_id}
        )

        if data and data.get("data"):
            return data["data"][0]

        return None

    # ==================================================
    # STREAM CHECK (BATCH - up to 100)
    # ==================================================

    async def check_streams_live(self, user_ids: list[str]) -> set[str]:

        if not user_ids:
            return set()

        # Twitch supports up to 100 user_id params
        params = [("user_id", uid) for uid in user_ids[:100]]

        data = await self.helix_request(
            "streams",
            params
        )

        if not data:
            return set()

        live_ids = {
            stream["user_id"]
            for stream in data.get("data", [])
        }

        return live_ids

    # ==================================================
    # BADGES
    # ==================================================

    async def fetch_badges(self):

        data = await self.helix_request("chat/badges/global")

        if not data:
            return []

        return data.get("data", [])

    # ==================================================
    # DROPS
    # ==================================================

    async def fetch_drops(self):

        data = await self.helix_request("entitlements/drops")

        if not data:
            return []

        return data.get("data", [])
