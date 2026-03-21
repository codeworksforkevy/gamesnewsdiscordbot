import discord
import logging
import json

from services.redis_client import redis_client
from services.twitch_cache import get_cached_stream
from utils.stream_diff import detect_changes
from services.guild_config import get_guild_config

logger = logging.getLogger("event_router")


# ==================================================
# STREAM ONLINE
# ==================================================

async def handle_stream_online(bot, event):

    login = event["broadcaster_user_login"].lower()

    new_stream = await get_cached_stream(login)

    if not new_stream:
        return

    redis_key = f"stream:meta:{login}"

    old_stream_raw = await redis_client.get(redis_key)
    old_stream = json.loads(old_stream_raw) if old_stream_raw else None

    changes = detect_changes(old_stream, new_stream)

    # update cache
    await redis_client.set(
        redis_key,
        json.dumps(new_stream),
        ex=60
    )

    # Embed
    embed = discord.Embed(
        title=new_stream["title"],
        url=f"https://twitch.tv/{login}",
        color=0x9146FF
    )

    # 🔥 CHANGE DETECTION MESSAGE
    if changes:
        change_text = ""

        if "title" in changes:
            change_text += f"📝 Title changed:\n{changes['title']['old']} → {changes['title']['new']}\n\n"

        if "game" in changes:
            change_text += f"🎮 Game changed:\n{changes['game']['old']} → {changes['game']['new']}"

        embed.description = change_text

    for guild in bot.guilds:

        config = await get_guild_config(bot.app_state.db, guild.id)
        if not config:
            continue

        channel = guild.get_channel(config["channel_id"])
        if not channel:
            continue

        content = None
        if config.get("enable_ping") and config.get("ping_role_id"):
            role = guild.get_role(config["ping_role_id"])
            if role:
                content = role.mention

        await channel.send(content=content, embed=embed)
