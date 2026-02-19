import os
import aiohttp
import logging

logger = logging.getLogger("subscription-manager")

# ---------------------------------------------------
# Helpers
# ---------------------------------------------------

def get_env():
    return {
        "client_id": os.getenv("TWITCH_CLIENT_ID"),
        "client_secret": os.getenv("TWITCH_CLIENT_SECRET"),
        "eventsub_secret": os.getenv("TWITCH_EVENTSUB_SECRET"),
        "broadcaster_id": os.getenv("TWITCH_BROADCASTER_ID"),
        "public_base_url": os.getenv("PUBLIC_BASE_URL"),
    }


def build_endpoint(public_base_url: str) -> str:
    return f"{public_base_url.rstrip('/')}/twitch/eventsub"


# ---------------------------------------------------
# Twitch API
# ---------------------------------------------------

async def get_app_token(client_id: str, client_secret: str) -> str:

    url = "https://id.twitch.tv/oauth2/token"

    params = {
        "client_id": client_id,
        "client_secret": client_secret,
        "grant_type": "client_credentials",
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(url, params=params) as resp:
            data = await resp.json()

            if "access_token" not in data:
                logger.error("Failed to get app token: %s", data)
                raise RuntimeError("Twitch token error")

            return data["access_token"]


async def get_existing_subscriptions(token: str, client_id: str):

    url = "https://api.twitch.tv/helix/eventsub/subscriptions"

    headers = {
        "Client-ID": client_id,
        "Authorization": f"Bearer {token}",
    }

    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers) as resp:
            return await resp.json()


async def create_subscription(
    token: str,
    client_id: str,
    broadcaster_id: str,
    callback_url: str,
    eventsub_secret: str,
):

    url = "https://api.twitch.tv/helix/eventsub/subscriptions"

    headers = {
        "Client-ID": client_id,
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    payload = {
        "type": "stream.online",
        "version": "1",
        "condition": {
            "broadcaster_user_id": broadcaster_id,
        },
        "transport": {
            "method": "webhook",
            "callback": callback_url,
            "secret": eventsub_secret,
        },
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(url, headers=headers, json=payload) as resp:
            data = await resp.json()
            logger.info("Subscription response: %s", data)
            return data


# ---------------------------------------------------
# Public entry
# ---------------------------------------------------

async def ensure_subscriptions():

    env = get_env()

    if not all([
        env["client_id"],
        env["client_secret"],
        env["eventsub_secret"],
        env["broadcaster_id"],
        env["public_base_url"],
    ]):
        logger.warning("Missing Twitch ENV variables.")
        return

    logger.info("Checking Twitch subscriptions...")

    endpoint = build_endpoint(env["public_base_url"])

    token = await get_app_token(
        env["client_id"],
        env["client_secret"],
    )

    existing = await get_existing_subscriptions(
        token,
        env["client_id"],
    )

    subs = existing.get("data", [])

    for sub in subs:
        if (
            sub["type"] == "stream.online"
            and sub["condition"].get("broadcaster_user_id") == env["broadcaster_id"]
        ):
            logger.info("Subscription already exists.")
            return

    logger.info("Creating new subscription...")
    await create_subscription(
        token,
        env["client_id"],
        env["broadcaster_id"],
        endpoint,
        env["eventsub_secret"],
    )

    logger.info("Subscription check complete.")
