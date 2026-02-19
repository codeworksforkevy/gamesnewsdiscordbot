import os
import aiohttp
import logging

logger = logging.getLogger("subscription-manager")

TWITCH_CLIENT_ID = os.getenv("TWITCH_CLIENT_ID")
TWITCH_CLIENT_SECRET = os.getenv("TWITCH_CLIENT_SECRET")
BROADCASTER_ID = os.getenv("TWITCH_BROADCASTER_ID")
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL")

EVENTSUB_ENDPOINT = f"{PUBLIC_BASE_URL}/twitch/eventsub"

async def get_app_token():
    url = "https://id.twitch.tv/oauth2/token"

    params = {
        "client_id": TWITCH_CLIENT_ID,
        "client_secret": TWITCH_CLIENT_SECRET,
        "grant_type": "client_credentials"
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(url, params=params) as resp:
            data = await resp.json()
            return data["access_token"]

async def get_existing_subscriptions(token):
    url = "https://api.twitch.tv/helix/eventsub/subscriptions"

    headers = {
        "Client-ID": TWITCH_CLIENT_ID,
        "Authorization": f"Bearer {token}"
    }

    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers) as resp:
            return await resp.json()

async def create_subscription(token):
    url = "https://api.twitch.tv/helix/eventsub/subscriptions"

    headers = {
        "Client-ID": TWITCH_CLIENT_ID,
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    payload = {
        "type": "stream.online",
        "version": "1",
        "condition": {
            "broadcaster_user_id": BROADCASTER_ID
        },
        "transport": {
            "method": "webhook",
            "callback": EVENTSUB_ENDPOINT,
            "secret": TWITCH_CLIENT_SECRET
        }
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(url, headers=headers, json=payload) as resp:
            data = await resp.json()
            logger.info("Subscription response: %s", data)
            return data

async def ensure_subscriptions():

    if not all([TWITCH_CLIENT_ID, TWITCH_CLIENT_SECRET, BROADCASTER_ID, PUBLIC_BASE_URL]):
        logger.warning("Missing Twitch ENV variables.")
        return

    logger.info("Checking Twitch subscriptions...")

    token = await get_app_token()

    existing = await get_existing_subscriptions(token)

    subs = existing.get("data", [])

    for sub in subs:
        if (
            sub["type"] == "stream.online"
            and sub["condition"].get("broadcaster_user_id") == BROADCASTER_ID
        ):
            logger.info("Subscription already exists.")
            return

    logger.info("Creating new subscription...")
    await create_subscription(token)
