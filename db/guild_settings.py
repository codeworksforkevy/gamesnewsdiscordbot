# db/guild_settings.py

import logging
from typing import Optional, Dict

logger = logging.getLogger("db.guild_settings")

_db = None


def set_db(db) -> None:
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
    Returns guild config. Checks guild_configs first, falls back to
    guild_settings for legacy rows.

    Channel logic:
      announce_channel_id  → stream live notifications
      games_channel_id     → free games / deals / Luna posts
                             falls back to announce_channel_id if not set
    """
    db = _get_db()

    row = await db.fetchrow(
        """
        SELECT guild_id, announce_channel_id, games_channel_id,
               ping_role_id, live_role_id,
               notify_enabled, enable_epic, enable_gog, enable_steam
        FROM guild_configs
        WHERE guild_id = $1
        """,
        guild_id,
    )

    if row:
        d = dict(row)
        # If games_channel_id not set, fall back to announce_channel_id
        if not d.get("games_channel_id"):
            d["games_channel_id"] = d.get("announce_channel_id")
        return d

    # Legacy table fallback
    row = await db.fetchrow(
        """
        SELECT guild_id, announce_channel_id,
               games_channel_id
        FROM guild_settings
        WHERE guild_id = $1
        """,
        guild_id,
    )

    if row:
        d = dict(row)
        if not d.get("games_channel_id"):
            d["games_channel_id"] = d.get("announce_channel_id")
        return d

    return None


# ==================================================
# WRITE
# ==================================================

async def upsert_guild_config(
    guild_id: int,
    announce_channel_id: int = None,
    games_channel_id: int    = None,
    ping_role_id: int        = None,
    live_role_id: int        = None,
) -> None:
    db = _get_db()

    await db.execute(
        """
        INSERT INTO guild_configs (
            guild_id, announce_channel_id, games_channel_id,
            ping_role_id, live_role_id
        )
        VALUES ($1, $2, $3, $4, $5)
        ON CONFLICT (guild_id) DO UPDATE SET
            announce_channel_id = COALESCE(EXCLUDED.announce_channel_id,
                                           guild_configs.announce_channel_id),
            games_channel_id    = COALESCE(EXCLUDED.games_channel_id,
                                           guild_configs.games_channel_id),
            ping_role_id        = COALESCE(EXCLUDED.ping_role_id,
                                           guild_configs.ping_role_id),
            live_role_id        = COALESCE(EXCLUDED.live_role_id,
                                           guild_configs.live_role_id),
            updated_at          = CURRENT_TIMESTAMP
        """,
        guild_id,
        announce_channel_id,
        games_channel_id,
        ping_role_id,
        live_role_id,
    )
