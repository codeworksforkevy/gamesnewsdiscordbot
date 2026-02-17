
import json
from pathlib import Path
from services.twitch import fetch_twitch_badges

CACHE_FILE = Path("data/twitch_badges_cache.json")

async def update_twitch_badges(session):
    badges = await fetch_twitch_badges(session)
    CACHE_FILE.parent.mkdir(exist_ok=True)
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(badges, f, indent=2)
