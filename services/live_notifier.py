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
    try:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        logger.error("Failed to save streamers.json: %s", e)


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

        # Duplicate protection
        if info.get("is_live"):
            logger.info("Already marked live, skipping duplicate.")
            continue

        discord_channel_id = info.get("channel_id")
        channel = bot.get_channel(discord_channel_id)

        if not channel:
            logger.warning("Channel not found: %s (Guild %s)", discord_channel_id, guild_id)
            continue

        # -------------------------------------------------
        # PERMISSION CHECK (Pre-flight)
        # -------------------------------------------------

        perms = channel.permissions_for(channel.guild.me)

        if not perms.view_channel:
            logger.error("Bot cannot view channel %s in guild %s", discord_channel_id, guild_id)
            continue

        if not perms.send_messages:
            logger.error("Bot cannot send messages in channel %s (Guild %s)", discord_channel_id, guild_id)
            continue

        if not perms.embed_links:
            logger.error("Bot cannot embed links in channel %s (Guild %s)", discord_channel_id, guild_id)
            continue

        # -------------------------------------------------
        # BUILD EMBED
        # -------------------------------------------------

        embed = discord.Embed(
            title=f"🔴 {display_name} is LIVE!",
            url=f"https://twitch.tv/{login}",
            description="Click to watch the stream.",
            color=0x9146FF,
            timestamp=datetime.datetime.utcnow()
        )

        embed.set_footer(text="Twitch Live Notification")

        # -------------------------------------------------
        # SEND
        # -------------------------------------------------

        try:
            await channel.send(embed=embed)

            # Persist live state
            info["is_live"] = True
            save_streamers(registry)

            logger.info(
                "Live notification sent | Guild: %s | Channel: %s | Streamer: %s",
                guild_id,
                discord_channel_id,
                display_name
            )

        except discord.Forbidden as e:
            logger.error("FORBIDDEN while sending live notification")
            logger.error("Guild ID: %s", guild_id)
            logger.error("Channel ID: %s", discord_channel_id)
            logger.error("Channel Name: %s", getattr(channel, "name", "Unknown"))
            logger.error("Bot Permissions: %s", perms)
            logger.error("Error: %s", e)

        except discord.HTTPException as e:
            logger.error("HTTPException while sending live notification")
            logger.error("Guild ID: %s", guild_id)
            logger.error("Channel ID: %s", discord_channel_id)
            logger.error("Error: %s", e)

        except Exception:
            logger.exception("Unexpected error while sending live notification")


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
            logger.info("Live state reset for %s in guild %s", broadcaster_id, guild_id)

    save_streamers(registry)
