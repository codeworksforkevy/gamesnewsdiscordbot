import os
import time
import asyncio
import logging
import aiohttp

logger = logging.getLogger("twitch-api")

TOKEN_URL = "https://id.twitch.tv/oauth2/token"
HELIX_BASE = "https://api.twitch.tv/helix"


class TwitchAPI:
    """
    High-performance Twitch API wrapper with:
    - Token caching
    - Retry logic
    - Rate limit handling
    - Async safe token refresh
    """

    def __init__(self, session: aiohttp.ClientSession):

        self.session = session

        self.client_id = os.getenv("TWITCH_CLIENT_ID")
        self.client_secret = os.getenv("TWITCH_CLIENT_SECRET")

        if not self.client_id or not self.client_secret:
            raise RuntimeError("TWITCH credentials missing")

        self._app_token: str | None = None
        self._expiry: float = 0

        self._lock = asyncio.Lock()

    # ==================================================
    # TOKEN MANAGEMENT
    # ==================================================

    async def get_app_token(self) -> str | None:

        async with self._lock:

            now = time.time()

            # Token still valid
            if self._app_token and now < self._expiry:
                return self._app_token

            logger.info("Refreshing Twitch app token...")

            payload = {
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "grant_type": "client_credentials"
            }

            try:
                async with self.session.post(
                    TOKEN_URL,
                    data=payload,
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as resp:

                    if resp.status != 200:
                        text = await resp.text()
                        logger.error(f"Token error {resp.status}: {text}")
                        return None

                    data = await resp.json()

                    self._app_token = data["access_token"]
                    expires_in = int(data.get("expires_in", 3600))

                    # Early expiry buffer
                    self._expiry = now + expires_in - 60

                    return self._app_token

            except Exception as e:
                logger.error(f"Token request exception: {e}")
                return None

    # ==================================================
    # CORE HELIX REQUEST
    # ==================================================

    async def helix_request(self, endpoint: str, params=None, retry=True):

        token = await self.get_app_token()
        if not token:
            return None

        headers = {
            "Client-ID": self.client_id,
            "Authorization": f"Bearer {token}"
        }

        url = f"{HELIX_BASE}/{endpoint}"

        try:
            async with self.session.get(
                url,
                headers=headers,
                params=params,
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:

                # Token expired → retry once
                if resp.status == 401 and retry:
                    logger.warning("401 detected → refreshing token")
                    self._app_token = None
                    await self.get_app_token()
                    return await self.helix_request(endpoint, params, retry=False)

                # Rate limit handling
                if resp.status == 429:
                    retry_after = int(resp.headers.get("Retry-After", 1))
                    logger.warning(f"Rate limited. Sleeping {retry_after}s")

                    await asyncio.sleep(retry_after)

                    return await self.helix_request(endpoint, params, retry=False)

                if resp.status != 200:
                    text = await resp.text()
                    logger.error(
                        f"Helix error {endpoint} | {resp.status} | {text}"
                    )
                    return None

                return await resp.json()

        except asyncio.TimeoutError:
            logger.error(f"Timeout on {endpoint}")
            return None

        except Exception as e:
            logger.error(f"Helix request error: {e}")
            return None

    # ==================================================
    # USER
    # ==================================================

    async def get_user_by_login(self, login: str):

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
    # STREAM STATUS
    # ==================================================

    async def get_stream(self, user_id: str):

        data = await self.helix_request(
            "streams",
            {"user_id": user_id}
        )

        if data and data.get("data"):
            return data["data"][0]

        return None

    async def get_streams(self, user_ids: list[str]) -> set[str]:

        if not user_ids:
            return set()

        params = [("user_id", uid) for uid in user_ids[:100]]

        data = await self.helix_request(
            "streams",
            params
        )

        if not data:
            return set()

        return {
            stream["user_id"]
            for stream in data.get("data", [])
        }

    # ==================================================
    # BADGES
    # ==================================================

    async def get_global_badges(self):

        data = await self.helix_request("chat/badges/global")

        if not data:
            return []

        return data.get("data", [])

    # ==================================================
    # DROPS (NOT SUPPORTED)
    # ==================================================

    async def get_drops(self):

        logger.warning("Drops require user OAuth → disabled")

        return []
