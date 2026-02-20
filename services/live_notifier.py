import discord
import json
import os
import logging
import datetime

logger = logging.getLogger("live-notifier")

DATA_FILE = "data/streamers.json"


# ==================================================
# STORAGE
# ==================================================

def load_streamers():
    if not os.path.exists(DATA_FILE):
        return {"guilds": {}}

    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error("Failed to load streamers.json: %s", e)
        return {"guilds": {}}


def save_streamers(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


# ==================================================
# LIVE NOTIFIER (EventSub stream.online)
# ==================================================

async def notify_live(bot, channel_id, event):
    """
    event = Twitch EventSub event payload
    """

    broadcaster_id = event.get("broadcaster_user_id")
    display_name = event.get("broadcaster_user_name")
    login = event.get("broadcaster_user_login")

    if not broadcaster_id:
        logger.warning("No broadcaster_user_id in event.")
        return

    registry = load_streamers()
    guilds = registry.get("guilds", {})

    # Multi-guild scan
    for guild_id, guild_data in guilds.items():

        streamers = guild_data.get("streamers", {})

        if broadcaster_id not in streamers:
            continue

        info = streamers[broadcaster_id]

        # Duplicate protection via persistent state
        if info.get("is_live"):
            logger.info("Already marked live, skipping duplicate.")
            continue

        discord_channel_id = info.get("channel_id")
        channel = bot.get_channel(discord_channel_id)

        if not channel:
            logger.warning("Channel not found: %s", discord_channel_id)
            continue

        # -------------------------------------------------
        # Build Simple Premium Embed
        # -------------------------------------------------

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

            # Persist live state
            info["is_live"] = True
            save_streamers(registry)

            logger.info("Live notification sent for %s", display_name)

        except Exception as e:
            logger.error("Failed to send live notification: %s", e)


# ==================================================
# OFFLINE RESET (EventSub stream.offline)
# ==================================================

async def mark_offline(event):
    broadcaster_id = event.get("broadcaster_user_id")

    if not broadcaster_id:
        return

    registry = load_streamers()
    guilds = registry.get("guilds", {})

    for guild_id, guild_data in guilds.items():

        streamers = guild_data.get("streamers", {})

        if broadcaster_id in streamers:
            streamers[broadcaster_id]["is_live"] = False

    save_streamers(registry)
    logger.info("Live state reset for %s", broadcaster_id)
