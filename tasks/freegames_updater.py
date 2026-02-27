import json
import logging
from pathlib import Path
from datetime import datetime, timezone

from services.epic import fetch_epic_free
from services.gog import fetch_gog_free
from services.humble import fetch_humble_free
from services.steam import fetch_steam_free
from services.luna import fetch_luna_free

logger = logging.getLogger("freegames-updater")

CACHE_FILE = Path("data/free_games_cache.json")


async def safe_fetch(label, coro):
    try:
        result = await coro
        logger.info("%s fetched: %s items", label, len(result))
        return result
    except Exception as e:
        logger.warning("%s fetch failed: %s", label, e)
        return []


async def update_free_games(session):

    epic = await safe_fetch("Epic", fetch_epic_free(session))
    gog = await safe_fetch("GOG", fetch_gog_free(session))
    humble = await safe_fetch("Humble", fetch_humble_free(session))
    steam = await safe_fetch("Steam", fetch_steam_free(session))
    luna = await safe_fetch("Luna", fetch_luna_free(session))

    all_games = epic + gog + humble + steam + luna

    payload = {
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "games": all_games
    }

    try:
        CACHE_FILE.parent.mkdir(exist_ok=True)

        temp_file = CACHE_FILE.with_suffix(".tmp")

        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=4)

        temp_file.replace(CACHE_FILE)

        logger.info("Free games cache updated. Total games: %s", len(all_games))

    except Exception as e:
        logger.exception("Failed to write free games cache: %s", e)
