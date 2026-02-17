
import json
from pathlib import Path
from services.epic import fetch_epic_free

CACHE_FILE = Path("data/free_games_cache.json")

async def update_free_games(session):
    games = await fetch_epic_free(session)
    CACHE_FILE.parent.mkdir(exist_ok=True)
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(games, f, indent=2)
