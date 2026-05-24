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

LIVE_TTL  = 60 * 60 * 6    # 6 hours — active livestream cache
META_TTL  = 300             # 5 minutes — stream metadata for change detection

# Color palette — consistent with Find a Curie embeds
COLOR_LIVE    = 0xFFB6C1   # Baby pink  — live announcement
COLOR_UPDATE  = 0xF5A623   # Amber      — stream updates
COLOR_OFFLINE = 0x1C1C2E   # Dark navy  — offline embed

# Known streamers — used as a fallback seed list on startup
# so EventSub subscriptions are always created even if the DB is empty.
KNOWN_STREAMERS: dict[str, str] = {
    "amble_may2002":    "623178384",
    "bigbootykennyx":   "481101604",
    "cxrrinajxyne":     "535859139",
    "ellefyi":          "639451042",
    "eziverse":         "617198890",
    "frasedisplays":    "54088839",
    "keats___":         "256599363",
    "mirellemistlight": "786543297",
    "mkaybecca":        "233809759",
    "mousey2975":       "231954099",
    "neledraaa":        "555678290",
    "niiaaah":          "1041575461",
    "pancitplease":     "766528698",
    "r1sky_90":         None,   # twitch_user_id unknown — lookup on first event
    "realgirlsdontgame": "535406506",
}

KEVKEVVY_LOGIN      = "kevkevvy"
KEVKEVVY_CHANNEL_ID = 1446562544612540645

# Redis key helpers
def _meta_key(login: str) -> str:   return f"stream:meta:{login}"
def _status_key(login: str) -> str: return f"stream:status:{login}"
def _msg_key(login: str, guild_id: int) -> str: return f"stream:msg:{login}:{guild_id}"
def _start_key(login: str) -> str:  return f"stream:start:{login}"


def _get_target_channel(guild: discord.Guild, config: dict, login: str) -> Optional[discord.TextChannel]:
    """Returns the correct announcement channel based on streamer login."""
    if login == KEVKEVVY_LOGIN:
        ch = guild.get_channel(KEVKEVVY_CHANNEL_ID)
        if ch:
            return ch
    ch_id = config.get("announce_channel_id")
    return guild.get_channel(ch_id) if ch_id else None


# ──────────────────────────────────────────────────────────────
# EMBED BUILDERS
# ──────────────────────────────────────────────────────────────

def _live_embed(login: str, user_name: str, stream: dict) -> discord.Embed:
    """Baby pink live announcement embed — Find a Curie style."""
    title      = stream.get("title") or "No title set"
    game       = stream.get("game_name") or "Just Chatting"
    started_at = stream.get("started_at", "")

    # Thumbnail with cache-busting for a fresh live preview
    thumbnail = (
        f"https://static-cdn.jtvnw.net/previews-ttv/live_user_{login}-1280x720.jpg"
        f"?t={int(time.time())}"
    )

    # Relative Discord timestamp
    ts_str = "just now"
    if started_at:
        try:
            from datetime import datetime
            dt = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
            ts_str = f"<t:{int(dt.timestamp())}:R>"
        except Exception:
            pass

    embed = discord.Embed(
        title=title,
        url=f"https://twitch.tv/{login}",
        color=COLOR_LIVE,
    )
    embed.set_author(
        name=f"🔴 {user_name} is live!",
        url=f"https://twitch.tv/{login}",
    )
    embed.add_field(name="🎮 Game",    value=game,   inline=True)
    embed.add_field(name="⏱️ Started", value=ts_str, inline=True)
    embed.set_image(url=thumbnail)
    embed.set_footer(text=f"twitch.tv/{login}")
    embed.timestamp = discord.utils.utcnow()
    return embed


def _change_embed(login: str, user_name: str, changes: dict) -> discord.Embed:
    """Amber embed for stream updates (title change or game switch)."""
    embed = discord.Embed(
        title="📡 Stream Updated",
        url=f"https://twitch.tv/{login}",
        color=COLOR_UPDATE,
    )
    embed.set_author(
        name=user_name,
        url=f"https://twitch.tv/{login}",
    )
    if "title" in changes:
        embed.add_field(
            name="📝 Title",
            value=f"~~{changes['title']['old']}~~\n→ **{changes['title']['new']}**",
            inline=False,
        )
    if "game" in changes:
        embed.add_field(
            name="🎮 Game",
            value=f"~~{changes['game']['old']}~~\n→ **{changes['game']['new']}**",
            inline=False,
        )
    embed.set_footer(text=f"twitch.tv/{login}")
    embed.timestamp = discord.utils.utcnow()
    return embed


def _offline_embed(login: str, user_name: str, start_ts: Optional[float]) -> discord.Embed:
    """Dark navy offline embed — Find a Curie style."""
    desc = f"**{user_name}** has ended their stream."
    if start_ts:
        mins  = int((time.time() - start_ts) / 60)
        hours = mins // 60
        rest  = mins % 60
        desc += f"\n\n🕐 Stream duration: **{hours}h {rest}m**"

    embed = discord.Embed(description=desc, color=COLOR_OFFLINE)
    embed.set_author(
        name=user_name,
        url=f"https://twitch.tv/{login}",
    )
    embed.set_footer(text=f"twitch.tv/{login}")
    embed.timestamp = discord.utils.utcnow()
    return embed


# ──────────────────────────────────────────────────────────────
# HELPER — SEND OR EDIT
# ──────────────────────────────────────────────────────────────

async def _send_or_edit(
    channel: discord.TextChannel,
    login: str,
    guild_id: int,
    content: Optional[str],
    embed: discord.Embed,
) -> None:
    """
    Edits the existing live message if it's still tracked in Redis,
    otherwise sends a new one.
    """
    msg_key = _msg_key(login, guild_id)
    stored  = await redis_client.get(msg_key)
    if stored:
        try:
            msg = await channel.fetch_message(int(stored))
            await msg.edit(content=content, embed=embed)
            return
        except Exception:
            pass  # Message was deleted or no longer reachable — send new
    msg = await channel.send(content=content, embed=embed)
    await redis_client.set(msg_key, str(msg.id), ttl=LIVE_TTL)


# ──────────────────────────────────────────────────────────────
# EVENT HANDLERS
# ──────────────────────────────────────────────────────────────

async def handle_stream_online(bot, event: dict) -> None:
    """
    Handles stream.online event.
    Uses Twitch's unique stream ID to prevent duplicate notifications.
    """
    login     = event["broadcaster_user_login"].lower()
    user_name = event.get("broadcaster_user_name", login)
    b_id      = event.get("broadcaster_user_id")
    stream_id = event.get("id", "live")  # Unique Twitch stream ID — prevents ghost locks

    # Skip if the same stream ID is already marked as active
    already_live_id = await redis_client.get(_status_key(login))
    if already_live_id == stream_id:
        logger.info(f"Duplicate stream.online ignored for {login} (same stream_id)")
        return

    await redis_client.set(_status_key(login), stream_id,        ttl=LIVE_TTL)
    await redis_client.set(_start_key(login),  str(time.time()), ttl=LIVE_TTL)

    # Twitch API sometimes lags slightly behind the online event
    new_stream = await get_cached_stream(login)
    if not new_stream:
        await asyncio.sleep(10)
        new_stream = await get_cached_stream(login)

    # Fallback if API still hasn't caught up
    if not new_stream:
        new_stream = {"title": "Live!", "game_name": "Unknown"}

    # Send announcement to all relevant guilds
    for guild in bot.guilds:
        config = await get_guild_config(guild.id)
        if not config:
            continue

        if b_id:
            await upsert_streamer(b_id, login, guild.id)

        channel = _get_target_channel(guild, config, login)
        if channel:
            role = (
                guild.get_role(config.get("ping_role_id"))
                if config.get("enable_ping")
                else None
            )
            await _send_or_edit(
                channel, login, guild.id,
                role.mention if role else None,
                _live_embed(login, user_name, new_stream),
            )


async def handle_stream_offline(bot, event: dict) -> None:
    """
    Handles stream.offline event.
    Sends dark navy offline embed and cleans up Redis keys.
    """
    login     = event["broadcaster_user_login"].lower()
    user_name = event.get("broadcaster_user_name", login)
    b_id      = event.get("broadcaster_user_id")

    if b_id:
        await set_stream_offline(b_id)

    # Retrieve start time before deleting keys
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
    """
    Handles channel.update event.
    Only posts an embed if there is an actual change and the stream is active.
    """
    login     = event["broadcaster_user_login"].lower()
    user_name = event.get("broadcaster_user_name", login)

    # Ignore updates if the streamer is currently offline
    if not await redis_client.get(_status_key(login)):
        return

    new_stream = await get_cached_stream(login)
    old_raw    = await redis_client.get(_meta_key(login))
    old_stream = json.loads(old_raw) if old_raw else None

    changes = detect_changes(old_stream, new_stream) if old_stream else {}
    if changes:
        await redis_client.set(_meta_key(login), json.dumps(new_stream), ttl=META_TTL)
        for guild in bot.guilds:
            ch = _get_target_channel(guild, await get_guild_config(guild.id), login)
            if ch:
                await ch.send(embed=_change_embed(login, user_name, changes))
