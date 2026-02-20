import os
import aiohttp
import logging

from services.twitch_api import get_app_access_token

logger = logging.getLogger("eventsub-manager")

TWITCH_CLIENT_ID = os.getenv("TWITCH_CLIENT_ID")
TWITCH_EVENTSUB_SECRET = os.getenv("TWITCH_EVENTSUB_SECRET")
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL")


async def create_subscription(broadcaster_id: str, sub_type: str):

    token = await get_app_access_token()

    if not token:
        logger.error("Could not obtain Twitch app access token.")
        return False

    callback_url = f"{PUBLIC_BASE_URL}/twitch/eventsub"

    url = "https://api.twitch.tv/helix/eventsub/subscriptions"

    payload = {
        "type": sub_type,
        "version": "1",
        "condition": {
            "broadcaster_user_id": broadcaster_id
        },
        "transport": {
            "method": "webhook",
            "callback": callback_url,
            "secret": TWITCH_EVENTSUB_SECRET
        }
    }

    headers = {
        "Client-ID": TWITCH_CLIENT_ID,
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload, headers=headers) as resp:

            text = await resp.text()

            if resp.status in (200, 202):
                logger.info("Subscription created: %s", sub_type)
                return True
            else:
                logger.error("Subscription failed (%s): %s", resp.status, text)
                return False


async def ensure_stream_subscriptions(broadcaster_id: str):
    await create_subscription(broadcaster_id, "stream.online")
    await create_subscription(broadcaster_id, "stream.offline")
