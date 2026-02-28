import os
import time
import asyncio
import logging
import aiohttp

logger = logging.getLogger("eventsub-manager")


class EventSubManager:

    def __init__(self, http_session: aiohttp.ClientSession):
        self.session = http_session

        self.client_id = os.getenv("TWITCH_CLIENT_ID")
        self.client_secret = os.getenv("TWITCH_CLIENT_SECRET")
        self.secret = os.getenv("TWITCH_EVENTSUB_SECRET")
        self.public_url = os.getenv("PUBLIC_BASE_URL")

        self._app_token = None
        self._expiry = 0
        self._token_lock = asyncio.Lock()

        if not self.public_url:
            raise RuntimeError("PUBLIC_BASE_URL missing")

    # ==================================================
    # APP TOKEN (CONCURRENCY SAFE)
    # ==================================================

    async def get_app_access_token(self):

        async with self._token_lock:

            now = time.time()

            if self._app_token and now < self._expiry:
                return self._app_token

            url = "https://id.twitch.tv/oauth2/token"

            payload = {
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "grant_type": "client_credentials"
            }

            async with self.session.post(url, data=payload) as resp:

                if resp.status != 200:
                    text = await resp.text()
                    logger.error("Token refresh failed: %s", text)
                    return None

                data = await resp.json()

                self._app_token = data["access_token"]
                expires_in = data.get("expires_in", 3600)

                self._expiry = now + expires_in - 60

                logger.info("Twitch app token refreshed.")

                return self._app_token

    # ==================================================
    # HEADERS
    # ==================================================

    async def _auth_headers(self):

        token = await self.get_app_access_token()

        if not token:
            raise RuntimeError("No Twitch app token")

        return {
            "Client-ID": self.client_id,
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }

    # ==================================================
    # CREATE SUBSCRIPTION
    # ==================================================

    async def create_subscription(self, broadcaster_id: str, sub_type: str):

        url = "https://api.twitch.tv/helix/eventsub/subscriptions"

        payload = {
            "type": sub_type,
            "version": "1",
            "condition": {
                "broadcaster_user_id": broadcaster_id
            },
            "transport": {
                "method": "webhook",
                "callback": f"{self.public_url}/twitch/eventsub",
                "secret": self.secret
            }
        }

        headers = await self._auth_headers()

        async with self.session.post(url, json=payload, headers=headers) as resp:

            text = await resp.text()

            if resp.status in (200, 202):
                logger.info("Subscription created: %s (%s)", sub_type, broadcaster_id)
                return True

            if resp.status == 409:
                logger.info("Subscription already exists: %s (%s)", sub_type, broadcaster_id)
                return True

            logger.error("Subscription failed (%s): %s", resp.status, text)
            return False

    # ==================================================
    # LIST SUBSCRIPTIONS
    # ==================================================

    async def list_subscriptions(self):

        url = "https://api.twitch.tv/helix/eventsub/subscriptions"
        headers = await self._auth_headers()

        async with self.session.get(url, headers=headers) as resp:

            if resp.status != 200:
                text = await resp.text()
                logger.error("List subscriptions failed: %s", text)
                return []

            data = await resp.json()
            return data.get("data", [])

    # ==================================================
    # ENSURE STREAM SUBS
    # ==================================================

    async def ensure_stream_subscriptions(self, broadcaster_id: str):

        await self.create_subscription(broadcaster_id, "stream.online")
        await self.create_subscription(broadcaster_id, "stream.offline")
