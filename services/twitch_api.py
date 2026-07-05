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
            raise RuntimeError("TWITCH_CLIENT_ID and TWITCH_CLIENT_SECRET must be set")

        self._token  = None
        self._expiry = 0
        self._lock   = asyncio.Lock()

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
                    self._token  = data["access_token"]
                    self._expiry = now + data["expires_in"] - 60
                    return self._token
            except Exception as e:
                logger.error(f"Failed to fetch Twitch token: {e}")
                raise

    async def request(self, endpoint: str, params: Optional[List[tuple]] = None) -> Any:
        token = await self.get_token()
        headers = {"Client-ID": self.client_id, "Authorization": f"Bearer {token}"}
        url = f"{HELIX}/{endpoint}"
        async with self.session.get(url, params=params, headers=headers) as resp:
            return await resp.json()

    # --- ADDED: Batch stream fetch for watchdog mechanism ---
    async def get_streams_by_ids(self, user_ids: List[str]) -> List[Dict]:
        """Fetch live stream data for a list of user IDs (batch processing)."""
        if not user_ids:
            return []
        
        all_live = []
        # Twitch API limits to 100 IDs per request
        for i in range(0, len(user_ids), 100):
            chunk = user_ids[i:i + 100]
            params = [("user_id", uid) for uid in chunk]
            data = await self.request("streams", params=params)
            if data and "data" in data:
                all_live.extend(data["data"])
        return all_live

    # ... (diğer metodların aynı kalıyor)
