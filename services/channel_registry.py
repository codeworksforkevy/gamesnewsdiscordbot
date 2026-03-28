"""
channel_registry.py
────────────────────────────────────────────────────────────────
Loads and exposes the list of active guild notification channels.

Note: this registry populates bot.app_state.channels but is not
currently used by event_router (which queries per-guild config).
Keep it for any code that needs a flat channel list (e.g. bulk
announcements, admin tools).
"""

import logging
from typing import List, Dict

logger = logging.getLogger("channel-registry")


# ──────────────────────────────────────────────────────────────
# LOAD
# ──────────────────────────────────────────────────────────────

async def load_channels(db, bot) -> None:
    """
    Loads all active guild notification channels into bot.app_state.channels.
    Call this during bot startup after the DB pool is ready.
    """
    try:
        rows = await db.fetch(
            """
            SELECT guild_id, channel_id
            FROM guild_notification_channels
            WHERE is_active = TRUE
            """
        )

        bot.app_state.channels: List[Dict] = [
            {
                "guild_id":   row["guild_id"],
                "channel_id": row["channel_id"],
            }
            for row in rows
        ]

        logger.info(
            "Channels loaded",
            extra={"extra_data": {"count": len(bot.app_state.channels)}},
        )

    except Exception as e:
        err = str(e)
        # Silently skip if the table doesn't exist yet — run migrations to create it
        if "guild_notification_channels" in err or "does not exist" in err:
            logger.info(
                "guild_notification_channels table not found — skipping "
                "(run database/schema.sql to create it)"
            )
        else:
            logger.error(
                "Failed to load channels",
                extra={"extra_data": {"error": err}},
            )
        bot.app_state.channels = []


# ──────────────────────────────────────────────────────────────
# SAFE GETTER
# ──────────────────────────────────────────────────────────────

def get_channels(bot) -> List[Dict]:
    """Returns the cached channel list, or an empty list if not loaded yet."""
    return getattr(bot.app_state, "channels", [])
