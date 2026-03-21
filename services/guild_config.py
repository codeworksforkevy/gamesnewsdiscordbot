import asyncpg


# ==================================================
# UPSERT CONFIG (GÜNCELLENDİ)
# ==================================================

async def upsert_guild_config(
    db: asyncpg.Pool,
    guild_id: int,
    channel_id: int,
    ping_role_id: int | None,
    live_role_id: int | None,
    enable_ping: bool = True
):

    await db.execute(
        """
        INSERT INTO guild_configs (
            guild_id,
            channel_id,
            ping_role_id,
            live_role_id,
            enable_ping
        )
        VALUES ($1, $2, $3, $4, $5)
        ON CONFLICT (guild_id)
        DO UPDATE SET
            channel_id = EXCLUDED.channel_id,
            ping_role_id = EXCLUDED.ping_role_id,
            live_role_id = EXCLUDED.live_role_id,
            enable_ping = EXCLUDED.enable_ping
        """,
        guild_id,
        channel_id,
        ping_role_id,
        live_role_id,
        enable_ping
    )


# ==================================================
# GET CONFIG
# ==================================================

async def get_guild_config(db: asyncpg.Pool, guild_id: int):

    return await db.fetchrow(
        "SELECT * FROM guild_configs WHERE guild_id=$1",
        guild_id
    )
