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
        logger.error(
            "Failed to load channels",
            extra={"extra_data": {"error": str(e)}},
        )
        bot.app_state.channels = []


# ──────────────────────────────────────────────────────────────
# SAFE GETTER
# ──────────────────────────────────────────────────────────────

def get_channels(bot) -> List[Dict]:
    """Returns the cached channel list, or an empty list if not loaded yet."""
    return getattr(bot.app_state, "channels", [])
