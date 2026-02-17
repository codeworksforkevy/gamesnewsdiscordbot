import json
import datetime as dt

from services.epic import fetch_epic_free
from services.gog import fetch_gog_free
from services.humble import fetch_humble_free
from services.steam import fetch_steam_free
from services.luna import fetch_luna_free


CACHE_FILE = "data/free_games_cache.json"


async def update_free_games(session):

    epic = await fetch_epic_free(session)
    gog = await fetch_gog_free(session)
    humble = await fetch_humble_free(session)
    steam = await fetch_steam_free(session)
    luna = await fetch_luna_free(session)

    all_games = epic + gog + humble + steam + luna

    payload = {
        "last_updated": dt.datetime.utcnow().isoformat(),
        "games": all_games
    }

    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=4)

    print("Total games cached:", len(all_games))
