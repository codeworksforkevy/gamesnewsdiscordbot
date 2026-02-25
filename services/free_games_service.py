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


# =========================================================
# FETCH FROM STEAM
# =========================================================

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

    for row in rows[:15]:

        title_el = row.select_one(".title")
        img_el = row.select_one("img")

        if not title_el:
            continue

        title = title_el.text.strip()
        url = row.get("href")
        thumbnail = img_el["src"] if img_el else None

        if not url:
            continue

        offers.append({
            "platform": "steam",
            "title": title,
            "url": url,
            "thumbnail": thumbnail
        })

    logger.info("Steam fetched %s games", len(offers))
    return offers


# =========================================================
# UPDATE DATABASE CACHE
# =========================================================

async def update_free_games_cache(session):

    pool = get_pool()

    games = await fetch_free_games_from_source(session)

    if not games:
        logger.warning("No games fetched from source.")
        return

    async with pool.acquire() as conn:

        for g in games:
            await conn.execute("""
                INSERT INTO free_games (platform, title, url, thumbnail)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT (platform, title)
                DO UPDATE SET
                    url = EXCLUDED.url,
                    thumbnail = EXCLUDED.thumbnail,
                    updated_at = NOW();
            """, g["platform"], g["title"], g["url"], g["thumbnail"])

    logger.info("Free games cache updated (%s items)", len(games))


# =========================================================
# READ FROM DATABASE
# =========================================================

async def get_cached_free_games():

    pool = get_pool()

    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT platform, title, url, thumbnail
            FROM free_games
            ORDER BY updated_at DESC
        """)

    return [dict(r) for r in rows]
