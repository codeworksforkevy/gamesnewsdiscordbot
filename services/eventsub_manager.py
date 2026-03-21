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
    # APP TOKEN
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
    # RETRY WRAPPER
    # ==================================================

    async def _post_with_retry(self, url, json, headers, retries=3):

        delay = 1

        for attempt in range(retries):

            async with self.session.post(url, json=json, headers=headers) as resp:

                text = await resp.text()

                if resp.status in (200, 202, 409):
                    return resp.status, text

                logger.warning(
                    "Retry %s failed (%s): %s",
                    attempt,
                    resp.status,
                    text
                )

            await asyncio.sleep(delay)
            delay *= 2

        return resp.status, text

    # ==================================================
    # CREATE SUB
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

        status, text = await self._post_with_retry(url, payload, headers)

        if status in (200, 202):
            logger.info("Subscription created: %s (%s)", sub_type, broadcaster_id)
            return True

        if status == 409:
            logger.info("Already exists: %s (%s)", sub_type, broadcaster_id)
            return True

        logger.error("Subscription failed (%s): %s", status, text)
        return False

    # ==================================================
    # FULL SETUP
    # ==================================================

    async def subscribe_all(self, broadcaster_id: str):

        await self.create_subscription(broadcaster_id, "stream.online")
        await self.create_subscription(broadcaster_id, "stream.offline")
        await self.create_subscription(broadcaster_id, "channel.update")

    # ==================================================
    # LIST
    # ==================================================

    async def list_subscriptions(self):

        url = "https://api.twitch.tv/helix/eventsub/subscriptions"
        headers = await self._auth_headers()

        async with self.session.get(url, headers=headers) as resp:

            if resp.status != 200:
                text = await resp.text()
                logger.error("List failed: %s", text)
                return []

            data = await resp.json()
            return data.get("data", [])
