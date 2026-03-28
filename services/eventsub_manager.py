"""
eventsub_manager.py
────────────────────────────────────────────────────────────────
Manages Twitch EventSub webhook subscriptions.

Improvements over original:
- Checks for duplicate subscriptions before creating a new one
- Subscribes to BOTH stream.online and stream.offline
- No wasteful backward-compat helper that opens a new session per call
- Config validated once at construction, not inside every method
"""

import logging
import os
from typing import Optional

import aiohttp

logger = logging.getLogger("eventsub")

TWITCH_EVENTSUB_URL = "https://api.twitch.tv/helix/eventsub/subscriptions"


class EventSubManager:

    def __init__(self, session: aiohttp.ClientSession):
        self.session   = session
        self.client_id = os.getenv("TWITCH_CLIENT_ID")
        self.token     = os.getenv("TWITCH_ACCESS_TOKEN")
        self.secret    = os.getenv("TWITCH_EVENTSUB_SECRET", "supersecret")

        # Derive callback URL — used by monitor.py
        self.callback_url = (
            os.getenv("TWITCH_EVENTSUB_CALLBACK_URL")
            or (
                f"https://{os.getenv('RAILWAY_PUBLIC_DOMAIN')}/eventsub"
                if os.getenv("RAILWAY_PUBLIC_DOMAIN") else None
            )
        )

        if not self.client_id or not self.token:
            raise RuntimeError(
                "TWITCH_CLIENT_ID and TWITCH_ACCESS_TOKEN must be set "
                "before creating EventSubManager"
            )

    # ──────────────────────────────────────────────────────────
    # INTERNAL HELPERS
    # ──────────────────────────────────────────────────────────

    @property
    def _headers(self) -> dict:
        return {
            "Client-ID":     self.client_id,
            "Authorization": f"Bearer {self.token}",
            "Content-Type":  "application/json",
        }

    async def _existing_subscriptions(self, broadcaster_id: str) -> list[str]:
        """
        Returns a list of subscription types already active for this broadcaster.
        Prevents duplicate subscriptions.
        """
        try:
            async with self.session.get(
                TWITCH_EVENTSUB_URL,
                headers=self._headers,
                params={"broadcaster_user_id": broadcaster_id},
            ) as resp:
                if resp.status != 200:
                    logger.warning(
                        "Could not fetch existing subscriptions",
                        extra={"extra_data": {"status": resp.status}},
                    )
                    return []

                data = await resp.json()
                return [
                    sub["type"]
                    for sub in data.get("data", [])
                    if sub.get("status") in ("enabled", "webhook_callback_verification_pending")
                ]

        except Exception as e:
            logger.exception(f"Error fetching existing subscriptions: {e}")
            return []

    async def _subscribe(
        self,
        event_type: str,
        broadcaster_user_id: str,
        callback_url: str,
    ) -> bool:
        """
        Creates a single EventSub subscription.
        Returns True on success.
        """
        payload = {
            "type":    event_type,
            "version": "1",
            "condition": {"broadcaster_user_id": broadcaster_user_id},
            "transport": {
                "method":   "webhook",
                "callback": callback_url,
                "secret":   self.secret,
            },
        }

        try:
            async with self.session.post(
                TWITCH_EVENTSUB_URL,
                headers=self._headers,
                json=payload,
            ) as resp:
                text = await resp.text()

                if resp.status >= 300:
                    logger.error(
                        "EventSub subscribe failed",
                        extra={"extra_data": {
                            "type":       event_type,
                            "broadcaster": broadcaster_user_id,
                            "status":     resp.status,
                            "response":   text,
                        }},
                    )
                    return False

                logger.info(
                    "EventSub subscribed",
                    extra={"extra_data": {
                        "type":       event_type,
                        "broadcaster": broadcaster_user_id,
                    }},
                )
                return True

        except Exception as e:
            logger.exception(f"EventSub request error ({event_type}): {e}")
            return False

    # ──────────────────────────────────────────────────────────
    # PUBLIC API
    # ──────────────────────────────────────────────────────────

    async def list_subscriptions(self) -> list:
        """
        Returns all active EventSub subscriptions from Twitch.
        Used by monitor.py to audit which broadcasters are subscribed.
        """
        try:
            async with self.session.get(
                TWITCH_EVENTSUB_URL,
                headers=self._headers,
            ) as resp:
                if resp.status != 200:
                    logger.warning(
                        f"list_subscriptions failed: HTTP {resp.status}"
                    )
                    return []
                data = await resp.json()
                return data.get("data", [])
        except Exception as e:
            logger.exception(f"list_subscriptions error: {e}")
            return []

    async def ensure_subscriptions(
        self,
        broadcaster_user_id: str,
        callback_url: str,
    ) -> None:
        """
        Subscribes to stream.online and stream.offline for the given
        broadcaster — skipping any that already exist.
        """
        existing = await self._existing_subscriptions(broadcaster_user_id)

        wanted = ["stream.online", "stream.offline"]

        for event_type in wanted:
            if event_type in existing:
                logger.info(
                    f"Subscription already active, skipping",
                    extra={"extra_data": {
                        "type":       event_type,
                        "broadcaster": broadcaster_user_id,
                    }},
                )
                continue

            await self._subscribe(event_type, broadcaster_user_id, callback_url)

    async def delete_subscription(self, subscription_id: str) -> None:
        """Removes a specific subscription by ID."""
        try:
            async with self.session.delete(
                f"{TWITCH_EVENTSUB_URL}/{subscription_id}",
                headers=self._headers,
            ) as resp:
                if resp.status == 204:
                    logger.info(f"Subscription deleted: {subscription_id}")
                else:
                    text = await resp.text()
                    logger.warning(
                        "Delete subscription failed",
                        extra={"extra_data": {
                            "id":     subscription_id,
                            "status": resp.status,
                            "body":   text,
                        }},
                    )
        except Exception as e:
            logger.exception(f"Error deleting subscription {subscription_id}: {e}")
