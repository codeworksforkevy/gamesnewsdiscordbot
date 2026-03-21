import logging

logger = logging.getLogger("twitch-router")


# ==================================================
# STREAM ONLINE
# ==================================================

async def handle_stream_online(bot, event):

    broadcaster_id = event["broadcaster_user_id"]

    stream_data = await bot.app_state.twitch_api.get_stream(broadcaster_id)

    if not stream_data:
        return

    db = bot.app_state.db

    records = await db.fetch(
        "SELECT guild_id, channel_id, role_id FROM streamers WHERE streamer_id=$1",
        broadcaster_id
    )

    for r in records:

        guild = bot.get_guild(r["guild_id"])
        if not guild:
            continue

        channel = guild.get_channel(r["channel_id"])
        if not channel:
            continue

        role = guild.get_role(r["role_id"]) if r["role_id"] else None

        # ==================================================
        # ROLE HANDLING
        # ==================================================

        # "Live" rolünü al
        live_role = discord.utils.get(guild.roles, name="Live")

        members = [m for m in guild.members if any(role.id == r["role_id"] for role in m.roles)]

        for member in members:

            try:
                if live_role:
                    await member.add_roles(live_role)

                if role:
                    await member.add_roles(role)

            except Exception as e:
                logger.error("Role assign failed: %s", e)

        # ==================================================
        # EMBED
        # ==================================================

        embed = discord.Embed(
            title=f"{event['broadcaster_user_name']} is LIVE!",
            description=stream_data.get("title", ""),
            color=0x89CFF0
        )

        if stream_data.get("thumbnail_url"):
            thumb = stream_data["thumbnail_url"].replace("{width}", "1280").replace("{height}", "720")
            embed.set_image(url=thumb)

        embed.add_field(
            name="Game",
            value=stream_data.get("game_name", "Unknown"),
            inline=True
        )

        embed.add_field(
            name="Watch",
            value=f"https://twitch.tv/{event['broadcaster_user_login']}",
            inline=False
        )

        await channel.send(
            content=f"@everyone 🎉",
            embed=embed
        )


# ==================================================
# STREAM OFFLINE
# ==================================================

async def handle_stream_offline(bot, event):

    broadcaster_id = event["broadcaster_user_id"]

    db = bot.app_state.db

    records = await db.fetch(
        "SELECT guild_id, role_id FROM streamers WHERE streamer_id=$1",
        broadcaster_id
    )

    for r in records:

        guild = bot.get_guild(r["guild_id"])
        if not guild:
            continue

        role = guild.get_role(r["role_id"]) if r["role_id"] else None

        live_role = discord.utils.get(guild.roles, name="Live")

        if not live_role:
            continue

        members = [m for m in guild.members if live_role in m.roles]

        for member in members:
            try:
                await member.remove_roles(live_role)
            except Exception as e:
                logger.error("Role remove failed: %s", e)
