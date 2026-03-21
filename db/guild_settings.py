# db/guild_settings.py

import logging
from typing import Optional, Dict

from core.state_manager import state

logger = logging.getLogger("db.guild_settings")


async def get_guild_config(guild_id: int) -> Optional[Dict]:
    pool = state.get_db_pool()

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT guild_id, ping_role_id, live_role_id, announce_channel_id
            FROM guild_configs
            WHERE guild_id = $1
            """,
            guild_id
        )

        if not row:
            return None

        return dict(row)


async def upsert_guild_config(
    guild_id: int,
    ping_role_id: int = None,
    live_role_id: int = None,
    announce_channel_id: int = None
):
    pool = state.get_db_pool()

    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO guild_configs (guild_id, ping_role_id, live_role_id, announce_channel_id)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (guild_id)
            DO UPDATE SET
                ping_role_id = EXCLUDED.ping_role_id,
                live_role_id = EXCLUDED.live_role_id,
                announce_channel_id = EXCLUDED.announce_channel_id
            """,
            guild_id,
            ping_role_id,
            live_role_id,
            announce_channel_id
        )
