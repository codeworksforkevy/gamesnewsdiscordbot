import discord
import logging
from services.guild_config import get_guild_config
from services.redis_client import redis_client
from services.twitch_cache import get_cached_stream

logger = logging.getLogger("event_router")


# ==================================================
# STREAM ONLINE
# ==================================================

async def handle_stream_online(bot, event):

    user_login = event["broadcaster_user_login"].lower()
    user_name = event["broadcaster_user_name"]

    logger.info(f"Stream online: {user_login}")

    # ✅ Redis flag
    await redis_client.set(f"stream:{user_login}", "online", ex=300)

    # ✅ Cached Twitch metadata
    stream = await get_cached_stream(user_login)

    title = stream.get("title") if stream else f"{user_name} is LIVE!"
    thumbnail = f"https://static-cdn.jtvnw.net/previews-ttv/live_user_{user_login}-1280x720.jpg"

    embed = discord.Embed(
        title=title,
        url=f"https://twitch.tv/{user_login}",
        color=0x9146FF
    )

    embed.set_image(url=thumbnail)

    # 🚀 Iterate guilds
    for guild in bot.guilds:

        config = await get_guild_config(bot.app_state.db, guild.id)
        if not config:
            continue

        channel = guild.get_channel(config["channel_id"])
        if not channel:
            continue

        role = guild.get_role(config["ping_role_id"])
        live_role = guild.get_role(config["live_role_id"])

        content = role.mention if (role and config["enable_ping"]) else None

        try:
            await channel.send(content=content, embed=embed)
        except Exception as e:
            logger.error(f"Send failed: {e}")

        # 🔥 ROLE ASSIGN (optimized)
        if live_role:

            for member in guild.members:

                if not member.nick:
                    continue

                if user_login in member.nick.lower():

                    try:
                        await member.add_roles(live_role)
                    except Exception as e:
                        logger.error(f"Role assign failed: {e}")


# ==================================================
# STREAM OFFLINE
# ==================================================

async def handle_stream_offline(bot, event):

    user_login = event["broadcaster_user_login"].lower()

    logger.info(f"Stream offline: {user_login}")

    # ❌ Redis cleanup
    await redis_client.delete(f"stream:{user_login}")

    for guild in bot.guilds:

        config = await get_guild_config(bot.app_state.db, guild.id)
        if not config:
            continue

        live_role = guild.get_role(config["live_role_id"])
        if not live_role:
            continue

        for member in guild.members:

            if not member.nick:
                continue

            if user_login in member.nick.lower():

                try:
                    await member.remove_roles(live_role)
                except Exception as e:
                    logger.error(f"Role remove failed: {e}")
