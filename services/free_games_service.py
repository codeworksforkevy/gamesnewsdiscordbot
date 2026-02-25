import asyncpg
import aiohttp
import logging
from services.db import get_pool

logger = logging.getLogger("free-games-service")


# ----------------------------------------
# EXAMPLE FETCH (Replace with your scraper)
# ----------------------------------------

async def fetch_free_games_from_source(session):
    """
    Buraya kendi Steam/Epic fetch logic'in gelecek.
    Bu örnek dummy data.
    """

    # Örnek veri (gerçek fetch ile değiştir)
    return [
        {
            "platform": "steam",
            "title": "Example Game",
            "url": "https://store.steampowered.com",
            "thumbnail": None
        }
    ]


# ----------------------------------------
# UPDATE DB CACHE
# ----------------------------------------

async def update_free_games_cache(session):
    pool = get_pool()

    games = await fetch_free_games_from_source(session)

    if not games:
        logger.warning("No games fetched.")
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


# ----------------------------------------
# READ FROM DB
# ----------------------------------------

async def get_cached_free_games():
    pool = get_pool()

    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT platform, title, url, thumbnail
            FROM free_games
            ORDER BY updated_at DESC
        """)

    return [dict(r) for r in rows]
