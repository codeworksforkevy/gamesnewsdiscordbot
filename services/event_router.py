import discord
from services.guild_config import get_guild_config
from services.redis_client import redis

async def handle_stream_online(bot, event):

    user_login = event["broadcaster_user_login"]
    user_name = event["broadcaster_user_name"]

    cache_key = f"stream:{user_login}"
    await redis.set(cache_key, "online", ex=300)

    # TODO: Twitch API → thumbnail + title
    title = f"{user_name} is LIVE!"
    thumbnail = f"https://static-cdn.jtvnw.net/previews-ttv/live_user_{user_login}-1280x720.jpg"

    for guild in bot.guilds:

        config = await get_guild_config(guild.id)
        if not config:
            continue

        channel = guild.get_channel(config["announce_channel_id"])
        role = guild.get_role(config["ping_role_id"])
        live_role = guild.get_role(config["live_role_id"])

        embed = discord.Embed(
            title=title,
            url=f"https://twitch.tv/{user_login}",
            color=0x9146FF
        )
        embed.set_image(url=thumbnail)

        content = role.mention if role else None

        await channel.send(content=content, embed=embed)

        # 🔥 LIVE ROLE
        for member in guild.members:
            if member.nick and user_login in member.nick.lower():
                if live_role:
                    await member.add_roles(live_role)

async def handle_stream_offline(bot, event):
    user_login = event["broadcaster_user_login"]

    for guild in bot.guilds:
        config = await get_guild_config(guild.id)
        if not config:
            continue

        live_role = guild.get_role(config["live_role_id"])

        for member in guild.members:
            if member.nick and user_login in member.nick.lower():
                if live_role:
                    await member.remove_roles(live_role)
