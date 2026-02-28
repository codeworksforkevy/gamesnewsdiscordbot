import discord
import logging
from datetime import datetime, timezone

from services.streamer_registry import (
    get_guilds_for_streamer,
    set_live_state
)

logger = logging.getLogger("live-notifier")


# ==================================================
# LIVE NOTIFIER
# ==================================================

async def notify_live(bot: discord.Client, guild_id, event: dict):
    """
    Sends live notification embed to all registered guild channels.

    Compatible with:
        notify_live(bot, None, event)
        notify_live(bot, guild_id, event)
    """

    if not event:
        logger.warning("notify_live called without event data.")
        return

    db = bot.app_state.db

    broadcaster_id = event.get("broadcaster_user_id")
    display_name = event.get("broadcaster_user_name")
    login = event.get("broadcaster_user_login")

    if not broadcaster_id:
        logger.warning("Event missing broadcaster_user_id.")
        return

    rows = await get_guilds_for_streamer(db, broadcaster_id)

    if not rows:
        logger.info(
            "No guilds registered",
            extra={"extra_data": {"broadcaster_id": broadcaster_id}}
        )
        return

    for row in rows:

        row_guild_id = row["guild_id"]
        channel_id = int(row["channel_id"])
        is_live = row["is_live"]

        # Skip if already marked live (race safety)
        if is_live:
            continue

        channel = bot.get_channel(channel_id)

        # Fallback fetch
        if not channel:
            try:
                channel = await bot.fetch_channel(channel_id)
            except Exception:
                logger.warning(
                    "Channel inaccessible",
                    extra={"extra_data": {"channel_id": channel_id}}
                )
                continue

        if not channel:
            continue

        perms = channel.permissions_for(channel.guild.me)

        if not (perms.send_messages and perms.embed_links):
            logger.error(
                "Missing permissions",
                extra={"extra_data": {"channel_id": channel_id}}
            )
            continue

        embed = discord.Embed(
            title=f"🔴 {display_name} is LIVE!",
            url=f"https://twitch.tv/{login}",
            description="Click to watch the stream.",
            color=0x9146FF,
            timestamp=datetime.now(timezone.utc)
        )

        embed.set_footer(text="Twitch Live Notification")

        try:
            await channel.send(embed=embed)

            await set_live_state(
                db,
                row_guild_id,
                broadcaster_id,
                True
            )

            logger.info(
                "Live notification sent",
                extra={
                    "extra_data": {
                        "broadcaster_id": broadcaster_id,
                        "guild_id": row_guild_id
                    }
                }
            )

        except Exception as e:
            logger.error(
                "Failed to send live notification",
                extra={
                    "extra_data": {
                        "error": str(e),
                        "channel_id": channel_id
                    }
                }
            )


# ==================================================
# OFFLINE HANDLER
# ==================================================

async def mark_offline(bot: discord.Client, event: dict):
    """
    Resets live state when stream goes offline.
    """

    if not event:
        logger.warning("mark_offline called without event data.")
        return

    db = bot.app_state.db

    broadcaster_id = event.get("broadcaster_user_id")

    if not broadcaster_id:
        logger.warning("Offline event missing broadcaster_user_id.")
        return

    rows = await get_guilds_for_streamer(db, broadcaster_id)

    if not rows:
        return

    for row in rows:
        await set_live_state(
            db,
            row["guild_id"],
            broadcaster_id,
            False
        )

    logger.info(
        "Live state reset",
        extra={"extra_data": {"broadcaster_id": broadcaster_id}}
    )
