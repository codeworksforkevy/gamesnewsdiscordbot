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
            raise RuntimeError("TWITCH_CLIENT_ID and TWITCH_CLIENT_SECRET must be set")

        self._token  = None
        self._expiry = 0
        self._lock   = asyncio.Lock()

    async def get_token(self) -> str:
        """Fetches and caches the OAuth2 token for Twitch API access."""
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
                    self._token  = data["access_token"]
                    self._expiry = now + data["expires_in"] - 60
                    return self._token
            except Exception as e:
                logger.error(f"Failed to fetch Twitch token: {e}")
                raise

    async def request(self, endpoint: str, params: Optional[List[tuple]] = None) -> Any:
        """Helper to perform authorized requests to Twitch Helix API."""
        token = await self.get_token()
        headers = {"Client-ID": self.client_id, "Authorization": f"Bearer {token}"}
        url = f"{HELIX}/{endpoint}"
        async with self.session.get(url, params=params, headers=headers) as resp:
            return await resp.json()

    # ──────────────────────────────────────────────────────────
    # WATCHDOG BATCH FETCHING
    # ──────────────────────────────────────────────────────────
    async def get_streams_by_ids(self, user_ids: List[str]) -> List[Dict]:
        """
        Fetch live stream data for a list of user IDs in batches of 100.
        Optimized for the Watchdog loop to check multiple streamers at once.
        """
        if not user_ids:
            return []
        
        all_live = []
        # Twitch API limits to 100 IDs per request; process in chunks
        for i in range(0, len(user_ids), 100):
            chunk = user_ids[i:i + 100]
            params = [("user_id", uid) for uid in chunk]
            
            data = await self.request("streams", params=params)
            if data and "data" in data:
                all_live.extend(data["data"])
                
        return all_live

    # ──────────────────────────────────────────────────────────
    # MISSING METHODS ADDED FOR LIVE COMMANDS
    # ──────────────────────────────────────────────────────────
    async def get_stream_metadata(self, username: str) -> Optional[Dict]:
        """Fetches live stream metadata for a specific user login."""
        data = await self.request("streams", params=[("user_login", username)])
        if data and data.get("data"):
            # Return the first stream object if they are live
            return data["data"][0]
        return None

    async def get_user(self, username: str) -> Optional[Dict]:
        """Fetches a single user's profile data."""
        data = await self.request("users", params=[("login", username)])
        if data and data.get("data"):
            return data["data"][0]
        return None

    async def get_users_by_logins(self, logins: List[str]) -> Dict[str, Dict]:
        """Fetches user data by logins and returns a dict mapped by login name."""
        if not logins:
            return {}
        params = [("login", login) for login in logins]
        data = await self.request("users", params=params)
        
        result = {}
        if data and data.get("data"):
            for user in data["data"]:
                # Map the user data to their lowercase login name for easy dictionary lookups
                result[user["login"].lower()] = user
        return result
