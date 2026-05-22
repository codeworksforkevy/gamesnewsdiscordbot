"""
events/stream_events.py
────────────────────────────────────────────────────────────────
Handles all Twitch EventSub events (online, offline, channel.update).
Merged community routing, API delay fallbacks, and DB sync.
"""

import asyncio
import json
import logging
import time
from typing import Optional

import discord

from db.guild_settings import get_guild_config
from db.streamer_queries import upsert_streamer, set_stream_offline
from services.redis_client import redis_client
from services.twitch_cache import get_cached_stream
from utils.stream_diff import detect_changes

logger = logging.getLogger("stream-events")

# ──────────────────────────────────────────────────────────────
# CONSTANTS & ROUTING
# ──────────────────────────────────────────────────────────────

LIVE_TTL  = 60 * 60 * 6    
META_TTL  = 300            

KEVKEVVY_LOGIN      = "kevkevvy"
KEVKEVVY_CHANNEL_ID = 1446562544612540645

def _meta_key(login: str) -> str: return f"stream:meta:{login}"
def _status_key(login: str) -> str: return f"stream:status:{login}"
def _msg_key(login: str, guild_id: int) -> str: return f"stream:msg:{login}:{guild_id}"
def _start_key(login: str) -> str: return f"stream:start:{login}"

def _get_target_channel(guild: discord.Guild, config: dict, login: str) -> Optional[discord.TextChannel]:
    if login == KEVKEVVY_LOGIN:
        ch = guild.get_channel(KEVKEVVY_CHANNEL_ID)
        if ch: return ch
    ch_id = config.get("announce_channel_id")
    return guild.get_channel(ch_id) if ch_id else None

# ──────────────────────────────────────────────────────────────
# EMBED BUILDERS
# ──────────────────────────────────────────────────────────────

def _live_embed(login: str, user_name: str, stream: dict) -> discord.Embed:
    title = stream.get("title") or "Başlık belirtilmedi"
    game = stream.get("game_name") or "Just Chatting"
    started_at = stream.get("started_at", "")
    
    thumbnail = f"https://static-cdn.jtvnw.net/previews-ttv/live_user_{login}-1280x720.jpg?t={int(time.time())}"
    
    ts_str = "now"
    if started_at:
        try:
            from datetime import datetime
            dt = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
            ts_str = f"<t:{int(dt.timestamp())}:R>"
        except: pass

    embed = discord.Embed(
        title=title,
        url=f"https://twitch.tv/{login}",
        color=0xFFB6C1
    )
    
    # Eksik olan yazar (Author) bloğu geri eklendi
    embed.set_author(name=f"{user_name} is live!", url=f"https://twitch.tv/{login}")
    
    # Alanlar (Fields) daha düzenli hale getirildi
    embed.add_field(name="🎮 Game", value=game, inline=True)
    embed.add_field(name="☕ Started", value=ts_str, inline=True)
    
    embed.set_image(url=thumbnail)
    embed.set_footer(text="Vibes: Very Cool")
    embed.timestamp = discord.utils.utcnow()
    return embed

def _change_embed(login: str, user_name: str, changes: dict) -> discord.Embed:
    embed = discord.Embed(
        title="📡 Stream Updated",
        url=f"https://twitch.tv/{login}",
        color=0xF5A623
    )
    embed.set_author(name=user_name, url=f"https://twitch.tv/{login}")
    
    if "title" in changes: 
        embed.add_field(name="📝 Title", value=f"~~{changes['title']['old']}~~\n→ **{changes['title']['new']}**", inline=False)
    if "game" in changes: 
        embed.add_field(name="🎮 Game", value=f"~~{changes['game']['old']}~~\n→ **{changes['game']['new']}**", inline=False)
        
    embed.set_footer(text=f"twitch.tv/{login}")
    embed.timestamp = discord.utils.utcnow()
    return embed

def _offline_embed(login: str, user_name: str, start_ts: Optional[float]) -> discord.Embed:
    desc = f"**{user_name}** has ended their stream."
    if start_ts:
        mins = int((time.time() - start_ts) / 60)
        desc += f"\n\nStream duration: **{mins//60}h {mins%60}m**"
        
    embed = discord.Embed(description=desc, color=0x6e6e6e)
    embed.set_author(name=user_name, url=f"https://twitch.tv/{login}")
    embed.set_footer(text=f"twitch.tv/{login}")
    return embed

# ──────────────────────────────────────────────────────────────
# LOGIC
# ──────────────────────────────────────────────────────────────

async def _send_or_edit(channel: discord.TextChannel, login: str, guild_id: int, content: Optional[str], embed: discord.Embed):
    msg_key = _msg_key(login, guild_id)
    stored = await redis_client.get(msg_key)
    if stored:
        try:
            msg = await channel.fetch_message(int(stored))
            await msg.edit(content=content, embed=embed)
            return
        except: pass
    msg = await channel.send(content=content, embed=embed)
    await redis_client.set(msg_key, str(msg.id), ttl=LIVE_TTL)

async def handle_stream_online(bot, event: dict) -> None:
    login = event["broadcaster_user_login"].lower()
    user_name = event.get("broadcaster_user_name", login)
    b_id = event.get("broadcaster_user_id")
    
    # YENİ: Twitch'ten gelen benzersiz yayın ID'si
    stream_id = event.get("id", "live") 

    # YENİ: Sadece string olarak "live" yerine, stream_id'yi kontrol et
    already_live_id = await redis_client.get(_status_key(login))
    if already_live_id == stream_id: 
        logger.info(f"Duplicate stream.online ignored for {login} (same stream_id)")
        return
        
    await redis_client.set(_status_key(login), stream_id, ttl=LIVE_TTL)
    await redis_client.set(_start_key(login), str(time.time()), ttl=LIVE_TTL)

    new_stream = await get_cached_stream(login)
    if not new_stream:
        await asyncio.sleep(10)
        new_stream = await get_cached_stream(login)
    
    if not new_stream:
        new_stream = {"title": "Yayında!", "game_name": "Bilinmiyor"}

    # DB & Notification
    for guild in bot.guilds:
        config = await get_guild_config(guild.id)
        if not config: continue
        
        if b_id: await upsert_streamer(b_id, login, guild.id)
        
        channel = _get_target_channel(guild, config, login)
        if channel:
            role = guild.get_role(config.get("ping_role_id")) if config.get("enable_ping") else None
            await _send_or_edit(channel, login, guild.id, role.mention if role else None, _live_embed(login, user_name, new_stream))

async def handle_stream_offline(bot, event: dict) -> None:
    login = event["broadcaster_user_login"].lower()
    user_name = event.get("broadcaster_user_name", login)
    b_id = event.get("broadcaster_user_id")
    if b_id: await set_stream_offline(b_id)
    
    start_ts = float(await redis_client.get(_start_key(login)) or 0)
    await redis_client.delete(_status_key(login), _meta_key(login), _start_key(login))
    
    embed = _offline_embed(login, user_name, start_ts if start_ts > 0 else None)
    for guild in bot.guilds:
        config = await get_guild_config(guild.id)
        ch = _get_target_channel(guild, config, login)
        if ch: 
            await redis_client.delete(_msg_key(login, guild.id))
            await ch.send(embed=embed)

async def handle_channel_update(bot, event: dict) -> None:
    login = event["broadcaster_user_login"].lower()
    user_name = event.get("broadcaster_user_name", login)
    
    if not await redis_client.get(_status_key(login)): return
    
    new_stream = await get_cached_stream(login)
    old_raw = await redis_client.get(_meta_key(login))
    old_stream = json.loads(old_raw) if old_raw else None
    
    changes = detect_changes(old_stream, new_stream) if old_stream else {}
    if changes:
        await redis_client.set(_meta_key(login), json.dumps(new_stream), ttl=META_TTL)
        for guild in bot.guilds:
            ch = _get_target_channel(guild, await get_guild_config(guild.id), login)
            if ch: await ch.send(embed=_change_embed(login, user_name, changes))
