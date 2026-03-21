import discord
import time
from datetime import datetime, timezone

from services.streamer_registry import get_guilds_for_streamer


async def notify_live(bot, guild_id, event):

    db = bot.app_state.db
    twitch_api = bot.app_state.twitch_api

    broadcaster_id = event["broadcaster_user_id"]

    stream = await twitch_api.get_stream(broadcaster_id)
    user = await twitch_api.get_user(broadcaster_id)

    if not stream:
        return

    rows = await get_guilds_for_streamer(db, broadcaster_id)

    for row in rows:

        if row["is_live"]:
            continue

        channel = bot.get_channel(int(row["channel_id"]))

        if not channel:
            continue

        thumbnail = stream["thumbnail_url"] \
            .replace("{width}", "1280") \
            .replace("{height}", "720")

        thumbnail += f"?t={int(time.time())}"

        embed = discord.Embed(
            title=f"🔴 {user['display_name']} is LIVE!",
            description=stream["title"],
            url=f"https://twitch.tv/{user['login']}",
            color=0x9146FF,
            timestamp=datetime.now(timezone.utc)
        )

        embed.set_author(
            name=user["display_name"],
            icon_url=user["profile_image_url"]
        )

        embed.add_field(
            name="Playing",
            value=stream["game_name"],
            inline=True
        )

        embed.set_image(url=thumbnail)

        content = None
        if row["role_id"]:
            content = f"<@&{row['role_id']}> 🔴 LIVE NOW!"

        msg = await channel.send(content=content, embed=embed)

        pool = db.get_pool()
        async with pool.acquire() as conn:
            await conn.execute("""
                UPDATE streamers
                SET is_live = TRUE,
                    last_title = $1,
                    last_game = $2,
                    message_id = $3
                WHERE guild_id = $4
                AND broadcaster_id = $5;
            """,
                stream["title"],
                stream["game_name"],
                msg.id,
                row["guild_id"],
                broadcaster_id
            )


# --------------------------------------------------
# CHANGE DETECTION
# --------------------------------------------------

async def handle_stream_update(bot, event):

    db = bot.app_state.db
    twitch_api = bot.app_state.twitch_api

    broadcaster_id = event["broadcaster_user_id"]

    rows = await get_guilds_for_streamer(db, broadcaster_id)

    stream = await twitch_api.get_stream(broadcaster_id)

    if not stream:
        return

    for row in rows:

        if not row["is_live"]:
            continue

        if stream["title"] == row["last_title"] and \
           stream["game_name"] == row["last_game"]:
            continue

        channel = bot.get_channel(int(row["channel_id"]))
        if not channel:
            continue

        try:
            msg = await channel.fetch_message(row["message_id"])
        except:
            continue

        embed = msg.embeds[0]
        embed.description = stream["title"]

        embed.set_field_at(
            0,
            name="Playing",
            value=stream["game_name"],
            inline=True
        )

        await msg.edit(embed=embed)


# --------------------------------------------------
# OFFLINE
# --------------------------------------------------

async def mark_offline(bot, event):

    db = bot.app_state.db
    broadcaster_id = event["broadcaster_user_id"]

    rows = await get_guilds_for_streamer(db, broadcaster_id)

    for row in rows:

        channel = bot.get_channel(int(row["channel_id"]))
        if not channel:
            continue

        try:
            msg = await channel.fetch_message(row["message_id"])
        except:
            continue

        embed = msg.embeds[0]
        embed.color = 0x2F3136
        embed.title = embed.title.replace("🔴", "⚫")

        await msg.edit(embed=embed)
