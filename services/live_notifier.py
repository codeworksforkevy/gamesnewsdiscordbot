import discord
import logging
import datetime

from services.streamer_registry import (
    get_guilds_for_streamer,
    set_live_state
)

logger = logging.getLogger("live-notifier")


# ==================================================
# LIVE NOTIFIER
# ==================================================

async def notify_live(bot, event):

    broadcaster_id = event.get("broadcaster_user_id")
    display_name = event.get("broadcaster_user_name")
    login = event.get("broadcaster_user_login")

    if not broadcaster_id:
        return

    rows = await get_guilds_for_streamer(broadcaster_id)

    for row in rows:
        guild_id = row["guild_id"]
        channel_id = int(row["channel_id"])
        is_live = row["is_live"]

        if is_live:
            continue

        channel = bot.get_channel(channel_id)

        if not channel:
            logger.warning("Channel not found: %s", channel_id)
            continue

        perms = channel.permissions_for(channel.guild.me)

        if not (perms.send_messages and perms.embed_links):
            logger.error("Missing permissions in channel %s", channel_id)
            continue

        embed = discord.Embed(
            title=f"🔴 {display_name} is LIVE!",
            url=f"https://twitch.tv/{login}",
            description="Click to watch the stream.",
            color=0x9146FF,
            timestamp=datetime.datetime.utcnow()
        )

        embed.set_footer(text="Twitch Live Notification")

        try:
            await channel.send(embed=embed)

            await set_live_state(guild_id, broadcaster_id, True)

            logger.info("Live notification sent for %s", display_name)

        except Exception as e:
            logger.error("Failed to send live notification: %s", e)


# ==================================================
# OFFLINE
# ==================================================

async def mark_offline(event):

    broadcaster_id = event.get("broadcaster_user_id")

    if not broadcaster_id:
        return

    rows = await get_guilds_for_streamer(broadcaster_id)

    for row in rows:
        await set_live_state(row["guild_id"], broadcaster_id, False)

    logger.info("Live state reset for %s", broadcaster_id)
