import os
import aiohttp
import asyncio
import logging
import time

logger = logging.getLogger("twitch-api")

TWITCH_CLIENT_ID = os.getenv("TWITCH_CLIENT_ID")
TWITCH_CLIENT_SECRET = os.getenv("TWITCH_CLIENT_SECRET")

TOKEN_URL = "https://id.twitch.tv/oauth2/token"
HELIX_BASE = "https://api.twitch.tv/helix"

_app_token = None
_token_expiry = 0
_session = None


# -------------------------------------------------
# SESSION MANAGEMENT
# -------------------------------------------------
async def get_session():
    global _session
    if _session is None or _session.closed:
        _session = aiohttp.ClientSession()
    return _session


async def close_session():
    global _session
    if _session and not _session.closed:
        await _session.close()


# -------------------------------------------------
# TOKEN MANAGEMENT (cached + expiry aware)
# -------------------------------------------------
async def get_app_token():
    global _app_token, _token_expiry

    if _app_token and time.time() < _token_expiry:
        return _app_token

    session = await get_session()

    params = {
        "client_id": TWITCH_CLIENT_ID,
        "client_secret": TWITCH_CLIENT_SECRET,
        "grant_type": "client_credentials"
    }

    async with session.post(TOKEN_URL, params=params) as resp:
        data = await resp.json()

        if resp.status != 200:
            logger.error("Failed to obtain Twitch token: %s", data)
            return None

        _app_token = data["access_token"]
        expires_in = data.get("expires_in", 3600)

        # expire 60 sec early to be safe
        _token_expiry = time.time() + expires_in - 60

        logger.info("Twitch app token refreshed.")

        return _app_token


# -------------------------------------------------
# GENERIC HELIX REQUEST
# -------------------------------------------------
async def helix_request(endpoint, params=None):
    token = await get_app_token()
    if not token:
        return None

    session = await get_session()

    headers = {
        "Client-ID": TWITCH_CLIENT_ID,
        "Authorization": f"Bearer {token}"
    }

    url = f"{HELIX_BASE}/{endpoint}"

    async with session.get(url, headers=headers, params=params) as resp:
        data = await resp.json()

        # Auto refresh on 401
        if resp.status == 401:
            logger.warning("Token expired, refreshing...")
            await get_app_token()
            return await helix_request(endpoint, params)

        if resp.status != 200:
            logger.error("Helix request failed: %s", data)
            return None

        return data


# -------------------------------------------------
# USER RESOLUTION
# -------------------------------------------------
async def resolve_user(login: str):
    """
    Resolve Twitch login -> user object
    """
    data = await helix_request("users", {"login": login})
    if data and data.get("data"):
        return data["data"][0]
    return None


async def get_user_by_id(user_id: str):
    """
    Fetch user object by ID
    """
    data = await helix_request("users", {"id": user_id})
    if data and data.get("data"):
        return data["data"][0]
    return None


# -------------------------------------------------
# STREAM CHECK
# -------------------------------------------------
async def check_stream_live(user_id: str):
    """
    Returns stream object if live, else None
    """
    data = await helix_request("streams", {"user_id": user_id})
    if data and data.get("data"):
        return data["data"][0]
    return None
