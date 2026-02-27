import json
import logging
from pathlib import Path

from services.twitch import fetch_twitch_badges

logger = logging.getLogger("twitch-updater")

CACHE_FILE = Path("data/twitch_badges_cache.json")


async def update_twitch_badges(session):

    try:
        badges = await fetch_twitch_badges(session)

        if not badges:
            logger.warning("No Twitch badges fetched. Cache not updated.")
            return

        CACHE_FILE.parent.mkdir(exist_ok=True)

        temp_file = CACHE_FILE.with_suffix(".tmp")

        # Atomic write
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(badges, f, indent=2)

        temp_file.replace(CACHE_FILE)

        logger.info("Twitch badges cache updated (%s items).", len(badges))

    except Exception as e:
        logger.exception("Failed to update Twitch badges: %s", e)
