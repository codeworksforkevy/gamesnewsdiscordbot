import aiohttp
import logging
from bs4 import BeautifulSoup
from services.db import get_pool

logger = logging.getLogger("free-games-service")

STEAM_URL = "https://store.steampowered.com/search/?maxprice=free&specials=1"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/121.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


# ----------------------------------------------------
# STEAM FETCH (Hardened)
# ----------------------------------------------------

async def fetch_free_games_from_source(session: aiohttp.ClientSession):

    try:
        async with session.get(
            STEAM_URL,
            headers=HEADERS,
            timeout=20
        ) as resp:

            if resp.status != 200:
                logger.error("Steam returned status %s", resp.status)
                return []

            html = await resp.text()

    except Exception as e:
        logger.error("Steam fetch failed: %s", e)
        return []

    soup = BeautifulSoup(html, "html.parser")

    rows = soup.select(".search_result_row")

    if not rows:
        logger.warning("Steam selector returned no rows.")
        return []

    offers = []

    for row in rows[:15]:  # limit to 15

        title_el = row.select_one(".title")
        img_el = row.select_one("img")

        if not title_el:
            continue

        title = title_el.text.strip()
        url = row.get("href")
        thumbnail = img_el["src"] if img_el else None

        # Extra safety
        if not url or "store.steampowered.com" not in url:
            continue

        offers.append({
            "platform": "steam",
            "title": title,
            "url": url,
            "thumbnail": thumbnail
        })

    logger.info("Steam fetched %s free games", len(offers))
    return offers
