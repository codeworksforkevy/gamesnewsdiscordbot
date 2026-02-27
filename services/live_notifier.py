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

    broadcaster_id = event.get("broadcaster_user_id")
    display_name = event.get("broadcaster_user_name")
    login = event.get("broadcaster_user_login")

    if not broadcaster_id:
        logger.warning("Event missing broadcaster_user_id.")
        return

    rows = await get_guilds_for_streamer(broadcaster_id)

    if not rows:
        logger.info("No guilds registered for broadcaster %s", broadcaster_id)
        return

    for row in rows:
        row_guild_id = row["guild_id"]
        channel_id = int(row["channel_id"])
        is_live = row["is_live"]

        # Skip if already marked live
        if is_live:
            continue

        channel = bot.get_channel(channel_id)

        # Fallback fetch if not cached
        if not channel:
            try:
                channel = await bot.fetch_channel(channel_id)
            except Exception:
                logger.warning("Channel not found or inaccessible: %s", channel_id)
                continue

        if not channel:
            continue

        # Permission check
        perms = channel.permissions_for(channel.guild.me)

        if not (perms.send_messages and perms.embed_links):
            logger.error("Missing send/embed permissions in channel %s", channel_id)
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

            await set_live_state(row_guild_id, broadcaster_id, True)

            logger.info("Live notification sent for %s", display_name)

        except Exception as e:
            logger.error("Failed to send live notification: %s", e)


# ==================================================
# OFFLINE HANDLER
# ==================================================

async def mark_offline(event: dict):
    """
    Resets live state when stream goes offline.
    """

    if not event:
        logger.warning("mark_offline called without event data.")
        return

    broadcaster_id = event.get("broadcaster_user_id")

    if not broadcaster_id:
        logger.warning("Offline event missing broadcaster_user_id.")
        return

    rows = await get_guilds_for_streamer(broadcaster_id)

    for row in rows:
        await set_live_state(row["guild_id"], broadcaster_id, False)

    logger.info("Live state reset for %s", broadcaster_id)
