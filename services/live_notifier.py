import discord
import json
import os
import logging
import datetime

logger = logging.getLogger("live-notifier")

DATA_FILE = "data/streamers.json"

# Runtime duplicate guard (restart sonrası sıfırlanır)
_announced_live = set()


# -------------------------------------------------
# LOAD WHITELIST
# -------------------------------------------------
def load_streamers():
    if not os.path.exists(DATA_FILE):
        logger.warning("streamers.json not found.")
        return {}

    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error("Failed to load streamers.json: %s", e)
        return {}


# -------------------------------------------------
# MAIN LIVE NOTIFIER
# -------------------------------------------------
async def notify_live(bot, channel_id, stream_data, user_data):
    """
    stream_data: Twitch Helix stream object
    user_data: Twitch Helix user object
    """

    broadcaster_id = stream_data.get("user_id")

    if not broadcaster_id:
        logger.warning("No broadcaster_id in stream_data.")
        return

    # Whitelist check
    streamers = load_streamers()
    if broadcaster_id not in streamers:
        logger.info("Streamer not whitelisted: %s", broadcaster_id)
        return

    # Duplicate guard
    if broadcaster_id in _announced_live:
        logger.info("Duplicate live event ignored for %s", broadcaster_id)
        return

    channel = bot.get_channel(channel_id)
    if not channel:
        logger.warning("Discord channel not found: %s", channel_id)
        return

    # -------------------------------------------------
    # Build Twitch Thumbnail
    # -------------------------------------------------
    thumbnail = stream_data.get("thumbnail_url", "")
    if "{width}" in thumbnail:
        thumbnail = thumbnail.replace("{width}", "1280").replace("{height}", "720")

    # -------------------------------------------------
    # Create Premium Embed
    # -------------------------------------------------
    embed = discord.Embed(
        title=f"🔴 {user_data['display_name']} is LIVE!",
        url=f"https://twitch.tv/{user_data['login']}",
        description=f"💻 **{stream_data.get('title', 'Live Now')}**",
        color=0x9146FF,
        timestamp=datetime.datetime.utcnow()
    )

    embed.add_field(
        name="🎮 Game",
        value=stream_data.get("game_name", "Unknown"),
        inline=True
    )

    embed.set_author(
        name=user_data["display_name"],
        icon_url=user_data.get("profile_image_url")
    )

    embed.set_image(url=thumbnail)

    embed.set_footer(text="Twitch Live Notification")

    # -------------------------------------------------
    # Send
    # -------------------------------------------------
    try:
        await channel.send(embed=embed)
        _announced_live.add(broadcaster_id)
        logger.info("Live notification sent for %s", user_data["display_name"])
    except Exception as e:
        logger.error("Failed to send live notification: %s", e)


# -------------------------------------------------
# OPTIONAL: OFFLINE RESET
# -------------------------------------------------
def mark_offline(broadcaster_id):
    """
    Call this when Twitch sends stream.offline event.
    This allows next live event to trigger again.
    """
    if broadcaster_id in _announced_live:
        _announced_live.remove(broadcaster_id)
        logger.info("Reset live state for %s", broadcaster_id)
