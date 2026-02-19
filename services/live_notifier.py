import discord
import json
import os
import logging

logger = logging.getLogger("live-notifier")

DATA_FILE = "data/streamers.json"

# Memory duplicate guard (restart sonrası reset olur — minimal sürüm)
_announced = set()

def load_streamers():
    if not os.path.exists(DATA_FILE):
        return {}
    with open(DATA_FILE, "r") as f:
        return json.load(f)

async def notify_live(bot, channel_id, event):

    streamer_id = event.get("broadcaster_user_id")

    if not streamer_id:
        return

    # duplicate guard
    if streamer_id in _announced:
        return

    streamers = load_streamers()

    if streamer_id not in streamers:
        return  # whitelist only

    streamer = streamers[streamer_id]

    channel = bot.get_channel(channel_id)
    if not channel:
        logger.warning("Channel not found.")
        return

    # Ultra clean premium embed
    embed = discord.Embed(
        title=f"🔴 {streamer['display_name']} is LIVE",
        url=f"https://twitch.tv/{streamer['login']}",
        description="Streaming now on Twitch",
        color=0x9146FF
    )

    embed.set_thumbnail(url=streamer["profile_image_url"])

    embed.set_image(
        url=f"https://static-cdn.jtvnw.net/previews-ttv/live_user_{streamer['login']}-1280x720.jpg"
    )

    embed.set_footer(text="Twitch Live Notification")

    await channel.send(embed=embed)

    _announced.add(streamer_id)
    logger.info("Live notification sent for %s", streamer["display_name"])
