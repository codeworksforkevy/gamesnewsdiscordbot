# db/guild_settings.py
#
# FIX: was importing from core/state_manager.py which is a separate
# singleton never populated by main.py — so get_db_pool() always raised
# "DB pool not initialized in AppState", causing every guild to fail
# during startup_sync.
#
# Now reads the pool directly from the Database object on app_state,
# matching exactly how every other part of the bot accesses the DB.

import logging
from typing import Optional, Dict

logger = logging.getLogger("db.guild_settings")

# Lazy reference — set by main.py after DB connects
_db = None


def set_db(db) -> None:
    """Called once from main.py after Database.connect() completes."""
    global _db
    _db = db


def _get_db():
    if _db is None:
        raise RuntimeError(
            "guild_settings DB not initialised — call set_db() from main.py"
        )
    return _db


# ==================================================
# READ
# ==================================================

async def get_guild_config(guild_id: int) -> Optional[Dict]:
    """
    Returns the guild config row from guild_configs, or None if not set.
    Checks both guild_configs (new) and guild_settings (legacy) tables.
    """
    db = _get_db()

    # Try guild_configs first (full-featured table)
    row = await db.fetchrow(
        """
        SELECT guild_id, announce_channel_id, ping_role_id, live_role_id,
               notify_enabled, enable_epic, enable_gog, enable_steam
        FROM guild_configs
        WHERE guild_id = $1
        """,
        guild_id,
    )

    if row:
        return dict(row)

    # Fall back to legacy guild_settings table
    row = await db.fetchrow(
        """
        SELECT guild_id, announce_channel_id
        FROM guild_settings
        WHERE guild_id = $1
        """,
        guild_id,
    )

    return dict(row) if row else None


# ==================================================
# WRITE
# ==================================================

async def upsert_guild_config(
    guild_id: int,
    announce_channel_id: int = None,
    ping_role_id: int = None,
    live_role_id: int = None,
) -> None:
    """Create or update guild config. Only provided fields are changed."""
    db = _get_db()

    await db.execute(
        """
        INSERT INTO guild_configs (
            guild_id, announce_channel_id, ping_role_id, live_role_id
        )
        VALUES ($1, $2, $3, $4)
        ON CONFLICT (guild_id) DO UPDATE SET
            announce_channel_id = COALESCE(EXCLUDED.announce_channel_id,
                                           guild_configs.announce_channel_id),
            ping_role_id        = COALESCE(EXCLUDED.ping_role_id,
                                           guild_configs.ping_role_id),
            live_role_id        = COALESCE(EXCLUDED.live_role_id,
                                           guild_configs.live_role_id),
            updated_at          = CURRENT_TIMESTAMP
        """,
        guild_id,
        announce_channel_id,
        ping_role_id,
        live_role_id,
    )
