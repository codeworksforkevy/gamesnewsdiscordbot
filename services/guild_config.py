async def upsert_guild_config(db, guild_id, channel_id, role_id):

    pool = db.get_pool()

    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO guild_config (guild_id, default_channel_id, default_role_id)
            VALUES ($1, $2, $3)
            ON CONFLICT (guild_id)
            DO UPDATE SET
                default_channel_id = EXCLUDED.default_channel_id,
                default_role_id = EXCLUDED.default_role_id;
        """, str(guild_id), str(channel_id), role_id)
