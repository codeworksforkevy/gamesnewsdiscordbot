import asyncpg


# ==================================================
# UPSERT CONFIG
# ==================================================

async def upsert_guild_config(db: asyncpg.Pool, guild_id: int, channel_id: int, role_id: int | None):

    await db.execute(
        """
        INSERT INTO guild_configs (guild_id, channel_id, role_id)
        VALUES ($1, $2, $3)
        ON CONFLICT (guild_id)
        DO UPDATE SET
            channel_id = EXCLUDED.channel_id,
            role_id = EXCLUDED.role_id
        """,
        guild_id,
        channel_id,
        role_id
    )


# ==================================================
# GET CONFIG
# ==================================================

async def get_guild_config(db: asyncpg.Pool, guild_id: int):

    return await db.fetchrow(
        "SELECT * FROM guild_configs WHERE guild_id=$1",
        guild_id
    )
