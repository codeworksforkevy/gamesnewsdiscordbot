# db/streamer_queries.py

import logging
from typing import Optional, Dict

from core.state_manager import state

logger = logging.getLogger("db.streamers")


async def upsert_streamer(
    broadcaster_id: str,
    twitch_login: str,
    guild_id: int
):
    pool = state.get_db_pool()

    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO streamers (broadcaster_id, is_live, title, game_name, last_updated)
            VALUES ($1, FALSE, NULL, NULL, NOW())
            ON CONFLICT (broadcaster_id)
            DO UPDATE SET
                twitch_login = EXCLUDED.twitch_login,
                guild_id = EXCLUDED.guild_id
            """,
            broadcaster_id,
            twitch_login,
            guild_id
        )


async def set_stream_live(
    broadcaster_id: str,
    title: str,
    game_name: str
):
    pool = state.get_db_pool()

    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE streamers
            SET is_live = TRUE,
                title = $2,
                game_name = $3,
                last_updated = NOW()
            WHERE broadcaster_id = $1
            """,
            broadcaster_id,
            title,
            game_name
        )


async def set_stream_offline(broadcaster_id: str):
    pool = state.get_db_pool()

    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE streamers
            SET is_live = FALSE,
                last_updated = NOW()
            WHERE broadcaster_id = $1
            """,
            broadcaster_id
        )


async def get_streamer(broadcaster_id: str) -> Optional[Dict]:
    pool = state.get_db_pool()

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT *
            FROM streamers
            WHERE broadcaster_id = $1
            """,
            broadcaster_id
        )

        return dict(row) if row else None
