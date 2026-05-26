"""
db/streamer_queries.py
────────────────────────────────────────────────────────────────
CRUD helpers for the streamers table.

Fix vs original:
- upsert_streamer INSERT listed twitch_login and guild_id in the VALUES
  list but the column list didn't include them — fixed.
"""

import logging
from typing import Optional, Dict

from core.state_manager import state

logger = logging.getLogger("db.streamers")


# ──────────────────────────────────────────────────────────────
# UPSERT
# ──────────────────────────────────────────────────────────────

async def upsert_streamer(
    broadcaster_id: str,
    twitch_login:   str,
    guild_id:       int,
) -> None:
    pool = state.get_db_pool()

    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO streamers (
                broadcaster_id,
                twitch_login,
                guild_id,
                is_live,
                title,
                game_name,
                last_updated
            )
            VALUES ($1, $2, $3, FALSE, NULL, NULL, NOW())
            ON CONFLICT (broadcaster_id) DO UPDATE SET
                twitch_login = EXCLUDED.twitch_login,
                guild_id     = EXCLUDED.guild_id,
                last_updated = NOW()
            """,
            broadcaster_id,
            twitch_login,
            guild_id,
        )

    logger.info(
        "Streamer upserted",
        extra={"extra_data": {
            "broadcaster_id": broadcaster_id,
            "twitch_login":   twitch_login,
        }},
    )


# ──────────────────────────────────────────────────────────────
# STATUS UPDATES
# ──────────────────────────────────────────────────────────────

async def set_stream_live(
    broadcaster_id: str,
    title:          str,
    game_name:      str,
) -> None:
    pool = state.get_db_pool()

    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE streamers
            SET is_live      = TRUE,
                title        = $2,
                game_name    = $3,
                last_updated = NOW()
            WHERE broadcaster_id = $1
            """,
            broadcaster_id,
            title,
            game_name,
        )


async def set_stream_offline(broadcaster_id: str) -> None:
    pool = state.get_db_pool()

    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE streamers
            SET is_live      = FALSE,
                title        = NULL,
                game_name    = NULL,
                last_updated = NOW()
            WHERE broadcaster_id = $1
            """,
            broadcaster_id,
        )


# ──────────────────────────────────────────────────────────────
# READ
# ──────────────────────────────────────────────────────────────

async def get_streamer(broadcaster_id: str) -> Optional[Dict]:
    pool = state.get_db_pool()

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT *
            FROM streamers
            WHERE broadcaster_id = $1
            """,
            broadcaster_id,
        )

        return dict(row) if row else None


async def get_all_live_streamers() -> list[Dict]:
    """Returns all streamers currently marked as live in the DB."""
    pool = state.get_db_pool()

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT *
            FROM streamers
            WHERE is_live = TRUE
            ORDER BY last_updated DESC
            """
        )

        return [dict(r) for r in rows]
