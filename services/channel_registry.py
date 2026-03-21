import logging

logger = logging.getLogger("channel-registry")


# ==================================================
# LOAD CHANNELS FROM DB
# ==================================================
async def load_channels(db, bot):
    """
    Loads all active guild channels into bot state
    """

    try:
        rows = await db.fetch("""
            SELECT guild_id, channel_id
            FROM guild_notification_channels
            WHERE is_active = TRUE
        """)

        bot.app_state.channels = [
            {
                "guild_id": row["guild_id"],
                "channel_id": row["channel_id"]
            }
            for row in rows
        ]

        logger.info(
            "Channels loaded",
            extra={"extra_data": {"count": len(bot.app_state.channels)}}
        )

    except Exception as e:
        logger.error(
            "Failed to load channels",
            extra={"extra_data": {"error": str(e)}}
        )


# ==================================================
# GET CHANNELS (SAFE ACCESS)
# ==================================================
def get_channels(bot):
    """
    Safe getter for channels
    """

    return getattr(bot.app_state, "channels", [])
