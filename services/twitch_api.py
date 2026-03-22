# services/twitch_api.py

import os
import time
import asyncio
import logging
import aiohttp

logger = logging.getLogger("twitch-api")

TOKEN_URL = "https://id.twitch.tv/oauth2/token"
HELIX = "https://api.twitch.tv/helix"


class TwitchAPI:

    def __init__(self, session: aiohttp.ClientSession):
        self.session = session

        self.client_id = os.getenv("TWITCH_CLIENT_ID")
        self.client_secret = os.getenv("TWITCH_CLIENT_SECRET")

        if not self.client_id or not self.client_secret:
            raise RuntimeError("Twitch credentials missing")

        self._token = None
        self._expiry = 0
        self._lock = asyncio.Lock()

    # ==================================================
    # TOKEN MANAGEMENT (THREAD SAFE)
    # ==================================================

    async def get_token(self):

        async with self._lock:

            now = time.time()

            if self._token and now < self._expiry:
                return self._token

            try:
                async with self.session.post(
                    TOKEN_URL,
                    data={
                        "client_id": self.client_id,
                        "client_secret": self.client_secret,
                        "grant_type": "client_credentials"
                    },
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as resp:

                    data = await resp.json()

                    if resp.status != 200:
                        raise RuntimeError(f"Twitch token error: {data}")

                    self._token = data["access_token"]
                    self._expiry = now + data.get("expires_in", 3600) - 60

                    logger.info("Twitch token refreshed")

                    return self._token

            except Exception as e:
                logger.error(f"Token fetch failed: {e}")
                raise

    # ==================================================
    # CORE REQUEST (RETRY + RATE LIMIT SAFE)
    # ==================================================

    async def request(self, endpoint, params=None, retries=3):

        url = f"{HELIX}/{endpoint}"

        for attempt in range(retries):

            try:
                token = await self.get_token()

                headers = {
                    "Client-ID": self.client_id,
                    "Authorization": f"Bearer {token}"
                }

                async with self.session.get(
                    url,
                    headers=headers,
                    params=params,
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as resp:

                    # RATE LIMIT
                    if resp.status == 429:
                        retry_after = int(resp.headers.get("Retry-After", 2))
                        logger.warning(f"Rate limited, retrying in {retry_after}s")
                        await asyncio.sleep(retry_after)
                        continue

                    if resp.status != 200:
                        text = await resp.text()
                        logger.warning(
                            f"Twitch API error {resp.status}: {text}"
                        )
                        return None

                    return await resp.json()

            except asyncio.TimeoutError:
                logger.warning("Twitch request timeout")

            except Exception as e:
                logger.warning(f"Twitch request failed: {e}")

            await asyncio.sleep(2 ** attempt)

        logger.error("Twitch request failed after retries")
        return None

    # ==================================================
    # USER LOOKUP (CRITICAL FOR /live add)
    # ==================================================

    async def get_user_by_login(self, login: str):

        data = await self.request(
            "users",
            {"login": login}
        )

        if not data or not data.get("data"):
            return None

        user = data["data"][0]

        return {
            "id": user["id"],
            "login": user["login"],
            "display_name": user["display_name"]
        }

    # ==================================================
    # STREAM STATUS
    # ==================================================

    async def get_stream(self, broadcaster_id: str):

        data = await self.request(
            "streams",
            {"user_id": broadcaster_id}
        )

        if not data or not data.get("data"):
            return None

        stream = data["data"][0]

        return {
            "id": stream.get("id"),
            "title": stream.get("title"),
            "game_name": stream.get("game_name"),
            "viewer_count": stream.get("viewer_count"),
            "started_at": stream.get("started_at"),
            "thumbnail": stream.get("thumbnail_url")
        }

    # ==================================================
    # LIGHTWEIGHT METADATA (LEGACY SUPPORT)
    # ==================================================

    async def get_stream_metadata(self, broadcaster_id):

        stream = await self.get_stream(broadcaster_id)

        if not stream:
            return None

        return {
            "title": stream["title"],
            "game": stream["game_name"]
        }
