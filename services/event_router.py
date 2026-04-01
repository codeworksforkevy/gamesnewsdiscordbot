import time
import logging
import discord
from datetime import datetime, timezone

from db.guild_settings import get_guild_config
from services.redis_client import redis_client
from services.twitch_cache import get_cached_stream

logger = logging.getLogger("event_router")

# ──────────────────────────────────────────────────────────────
# HELPERS
# ──────────────────────────────────────────────────────────────

def _status_key(user_login: str) -> str:
    return f"stream:status:{user_login.lower()}"

def _msg_key(user_login: str, guild_id: int) -> str:
    return f"stream:msg:{user_login.lower()}:{guild_id}"

def _format_duration(seconds: int) -> str:
    h, rem = divmod(int(seconds), 3600)
    m, s   = divmod(rem, 60)
    return f"{h}h {m}m {s}s" if h else f"{m}m {s}s"

KEVY_PINK = 0xFFB6C1

# ──────────────────────────────────────────────────────────────
# EMBED BUILDERS
# ──────────────────────────────────────────────────────────────

def _build_live_embed(user_login, user_name, stream, user_info=None) -> discord.Embed:
    title = stream.get("title", "No Title") if stream else "No Title"
    game  = stream.get("game_name") or stream.get("game") or "Creative / Art"
    
    if not game or str(game).lower() == "unknown":
        game = "Creative / Art"
        
    started_at = stream.get("started_at", "") if stream else ""
    stream_url = f"https://www.twitch.tv/{user_login}"

    ts_str = "now"
    if started_at:
        try:
            dt = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
            ts_str = f"<t:{int(dt.timestamp())}:R>"
        except: pass

    embed = discord.Embed(
        title=title,
        url=stream_url,
        description=f"Free on **Twitch**\n\n👩‍💻 Game: `{game}`\n☕ Started: {ts_str}",
        color=KEVY_PINK
    )
    
    icon_url = user_info.get("profile_image_url") if user_info else None
    embed.set_author(name=user_name, url=stream_url, icon_url=icon_url)

    raw_thumb = stream.get("thumbnail_url", "") if stream else ""
    if raw_thumb:
        thumb = raw_thumb.replace("{width}", "1280").replace("{height}", "720")
        embed.set_image(url=f"{thumb}?v={int(time.time())}")

    embed.set_footer(text="Stay Zen")
    return embed

def _build_offline_embed(user_login, user_name, stream) -> discord.Embed:
    now = datetime.now(timezone.utc)
    duration = "Unknown"
    if stream and stream.get("started_at"):
        try:
            start_dt = datetime.fromisoformat(stream["started_at"].replace("Z", "+00:00"))
            duration = _format_duration((now - start_dt).total_seconds())
        except: pass

    embed = discord.Embed(
        title=f"{user_name} was live",
        url=f"https://twitch.tv/{user_login}",
        description=f"*{stream.get('title', 'No title')}*",
        color=0x2f3136
    )
    embed.add_field(name="👩‍💻 Game", value=stream.get("game_name", "Art"), inline=True)
    embed.add_field(name="⏱️ Duration", value=duration, inline=True)
    embed.add_field(name="🎬 VOD", value=f"[Watch](https://twitch.tv/{user_login}/videos)", inline=True)
    return embed

# ──────────────────────────────────────────────────────────────
# HANDLERS & CORE FUNCTIONS
# ──────────────────────────────────────────────────────────────

async def get_stream_status(user_login: str) -> dict | None:
    """CRITICAL FIX: status_command.py expects this function."""
    user_login = user_login.lower()
    status = await redis_client.get(_status_key(user_login))
    if status == "live":
        return await get_cached_stream(user_login)
    return None

async def handle_stream_online(bot, event: dict) -> None:
    user_login = event["broadcaster_user_login"].lower()
    user_name  = event["broadcaster_user_name"]
    
    await redis_client.set(_status_key(user_login), "live", expire=21600)
    
    stream = None
    try:
        api = bot.app_state.twitch_api
        live = await api.get_streams_by_logins([user_login])
        if live:
            stream = live[0]
            from services.twitch_cache import cache_stream
            await cache_stream(user_login, stream)
    except: pass

    for guild in bot.guilds:
        try:
            row = await bot.app_state.db.fetchrow("SELECT target_channel_id FROM streamers WHERE twitch_login = $1 AND guild_id = $2", user_login, guild.id)
            ch_id = row["target_channel_id"] if row else (await get_guild_config(guild.id)).get("announce_channel_id")
            if not ch_id: continue

            channel = guild.get_channel(ch_id) or await bot.fetch_channel(ch_id)
            user_info = await bot.app_state.twitch_api.get_user_by_login(user_login)
            
            live_role = discord.utils.get(guild.roles, name="Live")
            msg = await channel.send(content=live_role.mention if live_role else None, embed=_build_live_embed(user_login, user_name, stream, user_info))
            await redis_client.set(_msg_key(user_login, guild.id), str(msg.id), expire=21600)
        except: pass

async def handle_stream_offline(bot, event: dict) -> None:
    user_login = event["broadcaster_user_login"].lower()
    stream = await get_cached_stream(user_login)
    await redis_client.delete(_status_key(user_login))

    for guild in bot.guilds:
        try:
            msg_id = await redis_client.get(_msg_key(user_login, guild.id))
            if not msg_id: continue
            
            row = await bot.app_state.db.fetchrow("SELECT target_channel_id FROM streamers WHERE twitch_login = $1 AND guild_id = $2", user_login, guild.id)
            ch_id = row["target_channel_id"] if row else (await get_guild_config(guild.id)).get("announce_channel_id")
            
            channel = guild.get_channel(ch_id) or await bot.fetch_channel(ch_id)
            msg = await channel.fetch_message(int(msg_id))
            await msg.edit(embed=_build_offline_embed(user_login, event["broadcaster_user_name"], stream))
            await redis_client.delete(_msg_key(user_login, guild.id))
        except: pass
