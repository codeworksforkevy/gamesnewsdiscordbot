# services/twitch_badges_fetcher.py
#
# Fetches Twitch global badges from the Helix API and writes them to
# data/twitch_badges_cache.json so the /twitch_badges command can read them.
#
# Called once at startup and then every 24 hours (badges rarely change).
# Add to main.py background tasks:
#   asyncio.create_task(badge_fetcher_loop(app_state), name="badge-fetcher")

import asyncio
import json
import logging
from pathlib import Path

logger = logging.getLogger("badge-fetcher")

CACHE_FILE   = Path("data/twitch_badges_cache.json")
POLL_INTERVAL = 86400   # 24 hours — badges almost never change


# ==================================================
# FETCH
# ==================================================

async def fetch_global_badges(twitch_api) -> list:
    """
    Fetch all global Twitch badges via the Helix API.
    Returns a list of badge dicts with title, description, thumbnail.
    """
    data = await twitch_api.request("chat/badges/global")

    if not data or not data.get("data"):
        logger.warning("Twitch global badges API returned empty")
        return []

    badges = []
    for badge_set in data["data"]:
        set_id    = badge_set.get("set_id", "")
        versions  = badge_set.get("versions", [])

        for version in versions:
            # Use the largest image available
            image_url = (
                version.get("image_url_4x")
                or version.get("image_url_2x")
                or version.get("image_url_1x")
                or ""
            )
            title = version.get("title") or set_id.replace("_", " ").title()

            badges.append({
                "id":          f"{set_id}/{version.get('id', '1')}",
                "title":       title,
                "description": version.get("description") or f"Twitch {title} badge",
                "thumbnail":   image_url,
                "set_id":      set_id,
                "version_id":  version.get("id", "1"),
            })

    logger.info(f"Fetched {len(badges)} Twitch global badges")
    return badges


# ==================================================
# WRITE CACHE
# ==================================================

def write_cache(badges: list) -> None:
    """Write badge list to the JSON cache file."""
    try:
        CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(badges, f, ensure_ascii=False, indent=2)
        logger.info(f"Badge cache written: {len(badges)} badges → {CACHE_FILE}")
    except Exception as e:
        logger.error(f"Failed to write badge cache: {e}")


# ==================================================
# BACKGROUND LOOP
# ==================================================

async def badge_fetcher_loop(app_state) -> None:
    """
    Background task. Fetches badges once at startup, then every 24 hours.
    Waits for the bot to be ready before the first fetch.
    """
    from services.twitch_api import TwitchAPI

    # Wait until the bot and Twitch API are initialised
    while not app_state.is_ready:
        await asyncio.sleep(2)

    logger.info("Badge fetcher: starting first fetch")

    ERROR_BASE = 60
    ERROR_MAX  = 3600
    error_count = 0

    while True:
        try:
            twitch_api = app_state.twitch_api
            if not twitch_api:
                logger.warning("Badge fetcher: Twitch API not ready yet")
                await asyncio.sleep(30)
                continue

            badges = await fetch_global_badges(twitch_api)

            if badges:
                write_cache(badges)
                error_count = 0
            else:
                logger.warning("Badge fetcher: empty response — keeping existing cache")

            await asyncio.sleep(POLL_INTERVAL)

        except asyncio.CancelledError:
            logger.info("Badge fetcher loop cancelled")
            break
        except Exception as e:
            error_count += 1
            backoff = min(ERROR_BASE * (2 ** (error_count - 1)), ERROR_MAX)
            logger.error(f"Badge fetcher error #{error_count}: {e} — retrying in {backoff}s")
            await asyncio.sleep(backoff)
