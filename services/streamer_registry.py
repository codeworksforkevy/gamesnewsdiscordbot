import logging
from typing import List

logger = logging.getLogger("streamer-registry")


# ==================================================
# ADD STREAMER
# ==================================================

async def add_streamer(db, guild_id: str, broadcaster_id: str, channel_id: str):
    """
    Adds or updates a streamer tracking entry.
    """

    pool = db.get_pool()

    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO streamers
            (guild_id, broadcaster_id, channel_id, is_live)
            VALUES ($1, $2, $3, FALSE)
            ON CONFLICT (guild_id, broadcaster_id)
            DO UPDATE SET channel_id = EXCLUDED.channel_id;
        """, str(guild_id), str(broadcaster_id), str(channel_id))

    logger.info(
        "Streamer added/updated",
        extra={
            "extra_data": {
                "guild_id": guild_id,
                "broadcaster_id": broadcaster_id
            }
        }
    )


# ==================================================
# REMOVE STREAMER
# ==================================================

async def remove_streamer(db, guild_id: str, broadcaster_id: str):
    """
    Removes a streamer from tracking.
    """

    pool = db.get_pool()

    async with pool.acquire() as conn:
        await conn.execute("""
            DELETE FROM streamers
            WHERE guild_id = $1
            AND broadcaster_id = $2;
        """, str(guild_id), str(broadcaster_id))

    logger.info(
        "Streamer removed",
        extra={
            "extra_data": {
                "guild_id": guild_id,
                "broadcaster_id": broadcaster_id
            }
        }
    )


# ==================================================
# GET STREAMERS BY BROADCASTER
# ==================================================

async def get_guilds_for_streamer(db, broadcaster_id: str) -> List:
    """
    Returns all guild tracking entries for a broadcaster.
    """

    pool = db.get_pool()

    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT guild_id, channel_id, is_live
            FROM streamers
            WHERE broadcaster_id = $1;
        """, str(broadcaster_id))

    return rows


# ==================================================
# SET LIVE STATE
# ==================================================

async def set_live_state(
    db,
    guild_id: str,
    broadcaster_id: str,
    state: bool
):
    """
    Updates live state for a specific guild + broadcaster.
    """

    pool = db.get_pool()

    async with pool.acquire() as conn:
        await conn.execute("""
            UPDATE streamers
            SET is_live = $1
            WHERE guild_id = $2
            AND broadcaster_id = $3;
        """, state, str(guild_id), str(broadcaster_id))

    logger.info(
        "Live state updated",
        extra={
            "extra_data": {
                "guild_id": guild_id,
                "broadcaster_id": broadcaster_id,
                "state": state
            }
        }
    )
