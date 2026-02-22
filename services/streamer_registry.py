from services.db import get_pool


# -------------------------------
# ADD STREAMER
# -------------------------------

async def add_streamer(guild_id, broadcaster_id, channel_id):
    pool = await get_pool()

    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO streamers (guild_id, broadcaster_id, channel_id)
            VALUES ($1, $2, $3)
            ON CONFLICT (guild_id, broadcaster_id)
            DO UPDATE SET channel_id = EXCLUDED.channel_id;
        """, str(guild_id), str(broadcaster_id), str(channel_id))


# -------------------------------
# REMOVE STREAMER
# -------------------------------

async def remove_streamer(guild_id, broadcaster_id):
    pool = await get_pool()

    async with pool.acquire() as conn:
        await conn.execute("""
            DELETE FROM streamers
            WHERE guild_id = $1 AND broadcaster_id = $2;
        """, str(guild_id), str(broadcaster_id))


# -------------------------------
# GET STREAMERS BY BROADCASTER
# -------------------------------

async def get_guilds_for_streamer(broadcaster_id):
    pool = await get_pool()

    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT guild_id, channel_id, is_live
            FROM streamers
            WHERE broadcaster_id = $1;
        """, str(broadcaster_id))

    return rows


# -------------------------------
# SET LIVE STATE
# -------------------------------

async def set_live_state(guild_id, broadcaster_id, state: bool):
    pool = await get_pool()

    async with pool.acquire() as conn:
        await conn.execute("""
            UPDATE streamers
            SET is_live = $1
            WHERE guild_id = $2 AND broadcaster_id = $3;
        """, state, str(guild_id), str(broadcaster_id))
