"""
db/guild_settings.py
────────────────────────────────────────────────────────────────
Guild configuration read/write helpers.

Improvements over original:
- Legacy table fallback now logs a deprecation warning so you know
  which guilds still need migrating
- upsert_guild_config validates that at least one field is provided
- All public functions are typed clearly
"""

import logging
from typing import Optional, Dict

logger = logging.getLogger("db.guild_settings")

_db = None


# ──────────────────────────────────────────────────────────────
# DB INJECTION
# ──────────────────────────────────────────────────────────────

def set_db(db) -> None:
    global _db
    _db = db


def _get_db():
    if _db is None:
        raise RuntimeError(
            "guild_settings DB not initialised — call set_db() from main.py"
        )
    return _db


# ──────────────────────────────────────────────────────────────
# READ
# ──────────────────────────────────────────────────────────────

async def get_guild_config(guild_id: int) -> Optional[Dict]:
    """
    Returns guild config dict, or None if the guild is not configured.

    Channel fields:
      announce_channel_id  — stream live / offline notifications
      games_channel_id     — free games, deals, Luna posts
                             falls back to announce_channel_id if not set
    """
    db = _get_db()

    # ── Primary table ───────────────────────────────────────────
    row = await db.fetchrow(
        """
        SELECT guild_id,
               announce_channel_id,
               games_channel_id,
               ping_role_id,
               live_role_id,
               notify_enabled,
               enable_ping,
               enable_epic,
               enable_gog,
               enable_steam
        FROM guild_configs
        WHERE guild_id = $1
        """,
        guild_id,
    )

    if row:
        d = dict(row)
        if not d.get("games_channel_id"):
            d["games_channel_id"] = d.get("announce_channel_id")
        return d

    # ── Legacy table fallback ───────────────────────────────────
    row = await db.fetchrow(
        """
        SELECT guild_id,
               announce_channel_id,
               games_channel_id
        FROM guild_settings
        WHERE guild_id = $1
        """,
        guild_id,
    )

    if row:
        logger.warning(
            "Guild is using legacy guild_settings table — please migrate to guild_configs",
            extra={"extra_data": {"guild_id": guild_id}},
        )
        d = dict(row)
        if not d.get("games_channel_id"):
            d["games_channel_id"] = d.get("announce_channel_id")
        return d

    return None


# ──────────────────────────────────────────────────────────────
# WRITE
# ──────────────────────────────────────────────────────────────

async def upsert_guild_config(
    guild_id: int,
    announce_channel_id: Optional[int] = None,
    games_channel_id:    Optional[int] = None,
    ping_role_id:        Optional[int] = None,
    live_role_id:        Optional[int] = None,
) -> None:
    """
    Inserts or updates a guild config row.
    At least one optional field must be provided.
    """
    if all(v is None for v in [
        announce_channel_id, games_channel_id, ping_role_id, live_role_id
    ]):
        raise ValueError(
            "upsert_guild_config: at least one field must be non-None"
        )

    db = _get_db()

    await db.execute(
        """
        INSERT INTO guild_configs (
            guild_id,
            announce_channel_id,
            games_channel_id,
            ping_role_id,
            live_role_id
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

    logger.info(
        "Guild config upserted",
        extra={"extra_data": {"guild_id": guild_id}},
    )
