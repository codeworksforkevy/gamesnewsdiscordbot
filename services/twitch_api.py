# services/twitch_api.py

import os
import time
import asyncio
import logging
import aiohttp
from typing import List, Optional, Dict, Any

logger = logging.getLogger("twitch-api")

TOKEN_URL = "https://id.twitch.tv/oauth2/token"
HELIX     = "https://api.twitch.tv/helix"


class TwitchAPI:

    def __init__(self, session: aiohttp.ClientSession):
        self.session = session

        self.client_id     = os.getenv("TWITCH_CLIENT_ID")
        self.client_secret = os.getenv("TWITCH_CLIENT_SECRET")

        if not self.client_id or not self.client_secret:
            raise RuntimeError(
                "TWITCH_CLIENT_ID and TWITCH_CLIENT_SECRET must be set"
            )

        self._token  = None
        self._expiry = 0
        self._lock   = asyncio.Lock()

    # ==================================================
    # TOKEN MANAGEMENT
    # ==================================================

    async def get_token(self) -> str:

        async with self._lock:

            now = time.time()

            if self._token and now < self._expiry:
                return self._token

            try:
                async with self.session.post(
                    TOKEN_URL,
                    data={
                        "client_id":     self.client_id,
                        "client_secret": self.client_secret,
                        "grant_type":    "client_credentials",
                    },
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:

                    data = await resp.json()

                    if resp.status != 200:
                        raise RuntimeError(f"Twitch token error: {data}")

                    self._token  = data["access_token"]
                    self._expiry = now + data.get("expires_in", 3600) - 60

                    logger.info("Twitch token refreshed")
                    return self._token

            except Exception as e:
                logger.error(f"Token fetch failed: {e}")
                raise

    # ==================================================
    # CORE REQUEST
    # ==================================================

    async def request(
        self,
        endpoint: str,
        params=None,
        retries: int = 3,
    ) -> Optional[Dict]:

        url = f"{HELIX}/{endpoint}"

        for attempt in range(retries):
            try:
                token = await self.get_token()

                headers = {
                    "Client-ID":     self.client_id,
                    "Authorization": f"Bearer {token}",
                }

                async with self.session.get(
                    url,
                    headers=headers,
                    params=params,
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:

                    if resp.status == 429:
                        retry_after = int(resp.headers.get("Retry-After", 2))
                        logger.warning(f"Rate limited — retrying in {retry_after}s")
                        await asyncio.sleep(retry_after)
                        continue

                    if resp.status != 200:
                        text = await resp.text()
                        logger.warning(f"Twitch API {resp.status}: {text[:200]}")
                        return None

                    return await resp.json()

            except asyncio.TimeoutError:
                logger.warning(f"Twitch request timeout (attempt {attempt + 1})")
            except Exception as e:
                logger.warning(f"Twitch request error: {e} (attempt {attempt + 1})")

            await asyncio.sleep(2 ** attempt)

        logger.error(f"Twitch request to {endpoint} failed after {retries} retries")
        return None

    # ==================================================
    # USER LOOKUP
    # FIX: now returns profile_image_url for embed avatars
    # ==================================================

    async def get_user_by_login(self, login: str) -> Optional[Dict]:

        data = await self.request("users", {"login": login.lower()})

        if not data or not data.get("data"):
            return None

        user = data["data"][0]

        return {
            "id":                user["id"],
            "login":             user["login"],
            "display_name":      user["display_name"],
            "profile_image_url": user.get("profile_image_url", ""),
            "description":       user.get("description", ""),
        }

    # ==================================================
    # SINGLE STREAM STATUS
    # ==================================================

    async def get_stream(self, broadcaster_id: str) -> Optional[Dict]:

        data = await self.request("streams", {"user_id": broadcaster_id})

        if not data or not data.get("data"):
            return None

        s = data["data"][0]

        return {
            "id":            s.get("id"),
            "user_login":    s.get("user_login"),
            "user_name":     s.get("user_name"),
            "title":         s.get("title"),
            "game_name":     s.get("game_name"),
            "viewer_count":  s.get("viewer_count", 0),
            "started_at":    s.get("started_at"),
            "thumbnail_url": s.get("thumbnail_url", ""),
            "language":      s.get("language", ""),
        }

    # ==================================================
    # BATCH STREAM LOOKUP
    # NEW: fetches up to 100 streamers in ONE API call.
    # This is what StreamMonitor needs — polling 10 streamers
    # one at a time would waste 10x the API quota.
    # ==================================================

    async def get_streams_by_logins(
        self,
        logins: List[str],
    ) -> List[Dict]:
        """
        Batch fetch live stream data for multiple Twitch logins.
        Returns only the streamers who are currently live.
        Twitch allows up to 100 logins per request.
        """
        if not logins:
            return []

        results = []

        # Twitch allows max 100 per request — chunk if needed
        chunk_size = 100
        for i in range(0, len(logins), chunk_size):
            chunk = logins[i:i + chunk_size]

            # Twitch accepts repeated 'user_login' params for batch lookup
            params = [("user_login", login.lower()) for login in chunk]

            data = await self.request("streams", params=params)

            if data and data.get("data"):
                for s in data["data"]:
                    results.append({
                        "id":            s.get("id"),
                        "user_login":    s.get("user_login", "").lower(),
                        "user_name":     s.get("user_name", ""),
                        "title":         s.get("title", ""),
                        "game_name":     s.get("game_name", ""),
                        "viewer_count":  s.get("viewer_count", 0),
                        "started_at":    s.get("started_at", ""),
                        "thumbnail_url": s.get("thumbnail_url", ""),
                        "language":      s.get("language", ""),
                    })

        return results

    # ==================================================
    # BATCH USER LOOKUP
    # Useful for /live list to show profile pictures
    # ==================================================

    async def get_users_by_logins(
        self,
        logins: List[str],
    ) -> Dict[str, Dict]:
        """
        Batch fetch user profiles for multiple logins.
        Returns dict of login → user data.
        """
        if not logins:
            return {}

        results = {}
        chunk_size = 100

        for i in range(0, len(logins), chunk_size):
            chunk = logins[i:i + chunk_size]
            params = [("login", login.lower()) for login in chunk]

            data = await self.request("users", params=params)

            if data and data.get("data"):
                for u in data["data"]:
                    results[u["login"].lower()] = {
                        "id":                u["id"],
                        "login":             u["login"],
                        "display_name":      u["display_name"],
                        "profile_image_url": u.get("profile_image_url", ""),
                        "description":       u.get("description", ""),
                    }

        return results

    # ==================================================
    # LIGHTWEIGHT METADATA (kept for backward compat)
    # ==================================================

    async def get_stream_metadata(self, broadcaster_id: str) -> Optional[Dict]:

        stream = await self.get_stream(broadcaster_id)

        if not stream:
            return None

        return {
            "title": stream["title"],
            "game":  stream["game_name"],
        }
