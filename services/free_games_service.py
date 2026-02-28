import logging
import datetime as dt

logger = logging.getLogger("free-games")


# ==================================================
# UPDATE FREE GAMES CACHE
# ==================================================

async def update_free_games_cache(db, epic, gog, humble, steam, luna):
    """
    Stores free games into database cache table.
    """

    all_games = epic + gog + humble + steam + luna

    payload = {
        "last_updated": dt.datetime.utcnow().isoformat(),
        "count": len(all_games),
        "games": all_games
    }

    pool = db.get_pool()

    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO free_games_cache (id, payload)
            VALUES (1, $1)
            ON CONFLICT (id)
            DO UPDATE SET payload = EXCLUDED.payload;
        """, payload)

    logger.info(
        "Free games cache updated",
        extra={
            "extra_data": {
                "count": len(all_games)
            }
        }
    )

    return len(all_games)
