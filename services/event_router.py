import time
import logging

import discord

from db.guild_settings import get_guild_config
from services.redis_client import redis_client
from services.twitch_cache import get_cached_stream

logger = logging.getLogger("event_router")

# ──────────────────────────────────────────────────────────────
# REDIS KEY HELPERS
# ──────────────────────────────────────────────────────────────

def _status_key(user_login: str) -> str:
    return f"stream:status:{user_login}"

def _msg_key(user_login: str, guild_id: int) -> str:
    return f"stream:msg:{user_login}:{guild_id}"

# TTL for live status flag (6 hours — generous for long streams)
LIVE_TTL = 60 * 60 * 6


# ──────────────────────────────────────────────────────────────
# EMBED BUILDER
# ──────────────────────────────────────────────────────────────

def _format_duration(seconds: int) -> str:
    """Convert seconds to human-readable duration like 1h 23m 45s."""
    h, rem = divmod(int(seconds), 3600)
    m, s   = divmod(rem, 60)
    if h:
        return f"{h}h {m}m {s}s"
    if m:
        return f"{m}m {s}s"
    return f"{s}s"


def _build_live_embed(
    user_login: str,
    user_name:  str,
    stream:     dict | None,
    user_info:  dict | None = None,
) -> discord.Embed:
    title        = (stream.get("title") if stream else None) or f"{user_name} is live!"
    game         = (stream.get("game_name") if stream else None) or "Unknown"
    viewer_count = stream.get("viewer_count", 0) if stream else 0
    started_at   = stream.get("started_at",  "") if stream else ""
    language     = (stream.get("language",   "") if stream else "").upper()

    # Cache-busted thumbnail — Discord always fetches the latest frame
    thumbnail = (
        f"https://static-cdn.jtvnw.net/previews-ttv/live_user_{user_login}"
        f"-1280x720.jpg?t={int(time.time())}"
    )

    # Live duration
    duration_str = ""
    if started_at:
        try:
            from datetime import datetime, timezone
            started  = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
            elapsed  = (datetime.now(timezone.utc) - started).total_seconds()
            duration_str = _format_duration(elapsed)
        except Exception:
            pass

    embed = discord.Embed(
        title=f"🔴  {title}",
        url=f"https://twitch.tv/{user_login}",
        color=0x9146FF,
    )

    # Author line with profile picture
    if user_info and user_info.get("profile_image_url"):
        embed.set_author(
            name=f"{user_name} is live on Twitch!",
            url=f"https://twitch.tv/{user_login}",
            icon_url=user_info["profile_image_url"],
        )
    else:
        embed.set_author(
            name=f"{user_name} is live on Twitch!",
            url=f"https://twitch.tv/{user_login}",
        )

    # Core fields
    embed.add_field(name="🎮 Game",    value=game,                    inline=True)
    embed.add_field(name="👥 Viewers", value=f"{viewer_count:,}",     inline=True)

    if duration_str:
        embed.add_field(name="⏱️ Live for", value=duration_str,       inline=True)

    if language and language not in ("", "OTHER"):
        embed.add_field(name="🌐 Language", value=language,           inline=True)

    embed.add_field(
        name="📺 Watch",
        value=f"[twitch.tv/{user_login}](https://twitch.tv/{user_login})",
        inline=True,
    )

    embed.set_image(url=thumbnail)
    embed.set_footer(text="🟣 Live on Twitch • Notifications by Find a Curie")
    embed.timestamp = discord.utils.utcnow()

    return embed


def _build_offline_embed(
    user_login:  str,
    user_name:   str,
    stream_info: dict | None = None,
    vod_url:     str  | None = None,
    duration:    str  | None = None,
    user_info:   dict | None = None,
) -> discord.Embed:
    """
    Rich offline embed showing stream summary, VOD link, and duration.
    Goes well beyond Sapphire's basic offline card.
    """
    embed = discord.Embed(color=0x6e6e6e)

    # Author with profile pic
    if user_info and user_info.get("profile_image_url"):
        embed.set_author(
            name=f"{user_name} was live on Twitch",
            url=f"https://twitch.tv/{user_login}",
            icon_url=user_info["profile_image_url"],
        )
    else:
        embed.set_author(
            name=f"{user_name} was live on Twitch",
            url=f"https://twitch.tv/{user_login}",
        )

    # Last stream title
    if stream_info and stream_info.get("title"):
        embed.description = f"*{stream_info['title']}*"

    # Game played
    if stream_info and stream_info.get("game_name"):
        embed.add_field(name="🎮 Game",     value=stream_info["game_name"], inline=True)

    # Stream duration
    if duration:
        embed.add_field(name="⏱️ Duration", value=duration,                inline=True)

    # VOD link
    if vod_url:
        embed.add_field(name="🎬 VOD",      value=f"[Click to watch]({vod_url})", inline=True)
    else:
        embed.add_field(
            name="🎬 VOD",
            value=f"[Check channel]( https://www.twitch.tv/{user_login}/videos)",
            inline=True,
        )

    embed.set_footer(text=f"⚫ Stream ended • twitch.tv/{user_login}")
    embed.timestamp = discord.utils.utcnow()

    return embed


# ──────────────────────────────────────────────────────────────
# STREAM ONLINE
# ──────────────────────────────────────────────────────────────

async def handle_stream_online(bot, event: dict):

    user_login = event["broadcaster_user_login"].lower()
    user_name  = event["broadcaster_user_name"]

    logger.info(
        f"🚀 DEBUG event_router: handle_stream_online called",
        extra={"extra_data": {"login": user_login, "event_keys": list(event.keys())}}
    )

    # ── Deduplication ──────────────────────────────────────────
    existing_status = await redis_client.get(_status_key(user_login))
    logger.info(f"🟡 DEBUG event_router: Redis status for {user_login} = {existing_status!r}")

    if existing_status == "live":
        logger.info(f"⚪ DEBUG event_router: duplicate event ignored for {user_login}")
        return

    await redis_client.set(_status_key(user_login), "live", ttl=LIVE_TTL)
    logger.info(f"🟢 DEBUG event_router: Redis live flag set for {user_login}")

    # ── Fetch stream metadata + user profile ──────────────────
    stream    = None
    user_info = None
    try:
        from core.state_manager import state
        api = state.get_bot().app_state.twitch_api
        if api:
            results   = await api.get_streams_by_logins([user_login])
            stream    = results[0] if results else None
            user_info = await api.get_user_by_login(user_login)
    except Exception as e:
        logger.warning(f"🟡 DEBUG event_router: metadata fetch failed ({e}) — using fallback")

    if not stream:
        try:
            stream = await get_cached_stream(user_login)
        except Exception:
            pass

    logger.info(
        f"🟢 DEBUG event_router: stream={stream.get('title') if stream else None} | "
        f"game={stream.get('game_name') if stream else None} | "
        f"viewers={stream.get('viewer_count') if stream else None}"
    )

    # Store stream info in Redis for offline embed
    if stream:
        try:
            import json as _json
            await redis_client.set(
                f"stream:last:{user_login}",
                _json.dumps({
                    "title":      stream.get("title"),
                    "game_name":  stream.get("game_name"),
                    "started_at": stream.get("started_at"),
                }),
                ttl=LIVE_TTL,
            )
        except Exception:
            pass

    embed = _build_live_embed(user_login, user_name, stream, user_info)

    # ── Per-guild dispatch ─────────────────────────────────────
    logger.info(f"🟢 DEBUG event_router: iterating {len(bot.guilds)} guild(s)")

    for guild in bot.guilds:

        config = await get_guild_config(guild.id)
        logger.info(
            f"🟡 DEBUG event_router: guild={guild.name} | "
            f"config={'found' if config else 'MISSING'} | "
            f"announce_channel_id={config.get('announce_channel_id') if config else None}"
        )

        if not config:
            logger.warning(f"🔴 DEBUG event_router: no config for guild {guild.name} ({guild.id}) — skipping")
            continue

        channel = guild.get_channel(config.get("announce_channel_id"))
        logger.info(
            f"🟡 DEBUG event_router: channel lookup → "
            f"{'found: ' + str(channel) if channel else 'NOT FOUND in cache — trying fetch'}"
        )

        if not channel:
            try:
                channel = await bot.fetch_channel(config.get("announce_channel_id"))
                logger.info(f"🟢 DEBUG event_router: channel fetched via API — {channel}")
            except Exception as e:
                logger.error(
                    f"🔴 DEBUG event_router: channel {config.get('announce_channel_id')} "
                    f"not found for guild {guild.name} — {e}"
                )
                continue

        role      = guild.get_role(config.get("ping_role_id"))
        live_role = guild.get_role(config.get("live_role_id"))
        content   = role.mention if (role and config.get("enable_ping")) else None

        msg_key    = _msg_key(user_login, guild.id)
        stored_msg = await redis_client.get(msg_key)

        if stored_msg:
            try:
                msg_id  = int(stored_msg)
                message = await channel.fetch_message(msg_id)
                await message.edit(content=content, embed=embed)
                logger.info(f"✅ DEBUG event_router: edited existing embed for {user_login} in {guild.name}")
            except Exception as e:
                logger.warning(f"🟡 DEBUG event_router: could not edit message ({e}) — re-sending")
                stored_msg = None

        if not stored_msg:
            try:
                message = await channel.send(content=content, embed=embed)
                await redis_client.set(msg_key, str(message.id), ttl=LIVE_TTL)
                logger.info(f"✅ DEBUG event_router: posted live notification for {user_login} in {guild.name}")
            except Exception as e:
                logger.error(f"🔴 DEBUG event_router: send failed in {guild.name} — {e}")

        if live_role:
            for member in guild.members:
                if member.bot:
                    continue
                if not member.nick:
                    continue
                if user_login in member.nick.lower():
                    try:
                        await member.add_roles(live_role)
                    except Exception as e:
                        logger.error(f"🔴 DEBUG event_router: role assign failed for {member} — {e}")


# ──────────────────────────────────────────────────────────────
# STREAM OFFLINE
# ──────────────────────────────────────────────────────────────

async def handle_stream_offline(bot, event: dict):

    user_login = event["broadcaster_user_login"].lower()
    user_name  = event["broadcaster_user_name"]

    logger.info(f"Stream offline: {user_login}")

    # ── Clear Redis live flag ───────────────────────────────────
    await redis_client.delete(_status_key(user_login))

    # ── Fetch last stream info + user profile + VOD ─────────────
    stream_info = None
    user_info   = None
    vod_url     = None
    duration    = None

    try:
        import json as _json
        raw = await redis_client.get(f"stream:last:{user_login}")
        if raw:
            stream_info = _json.loads(raw)
            # Calculate duration from stored started_at
            if stream_info.get("started_at"):
                from datetime import datetime, timezone
                started = datetime.fromisoformat(
                    stream_info["started_at"].replace("Z", "+00:00")
                )
                elapsed  = (datetime.now(timezone.utc) - started).total_seconds()
                duration = _format_duration(elapsed)
    except Exception:
        pass

    try:
        from core.state_manager import state
        api = state.get_bot().app_state.twitch_api
        if api:
            user_info = await api.get_user_by_login(user_login)
            # Fetch latest VOD
            vod_data = await api.request(
                "videos",
                params={"user_id": user_info["id"], "type": "archive", "first": 1}
            ) if user_info else None
            if vod_data and vod_data.get("data"):
                vod_url = vod_data["data"][0].get("url")
    except Exception as e:
        logger.warning(f"Could not fetch VOD for {user_login}: {e}")

    # ── Send offline notice & remove live role per guild ───────
    for guild in bot.guilds:

        config = await get_guild_config(guild.id)
        if not config:
            continue

        channel   = guild.get_channel(config.get("announce_channel_id"))
        live_role = guild.get_role(config.get("live_role_id"))

        # Post offline embed
        if channel:
            try:
                offline_embed = _build_offline_embed(
                    user_login, user_name,
                    stream_info=stream_info,
                    vod_url=vod_url,
                    duration=duration,
                    user_info=user_info,
                )
                await channel.send(embed=offline_embed)
            except Exception as e:
                logger.error(f"Offline notice failed for guild {guild.id}: {e}")

        # Clean up stored message ID
        msg_key = _msg_key(user_login, guild.id)
        await redis_client.delete(msg_key)

        # Remove live role
        if live_role:
            for member in guild.members:
                if member.bot:
                    continue
                if not member.nick:
                    continue
                if user_login in member.nick.lower():
                    try:
                        await member.remove_roles(live_role)
                    except Exception as e:
                        logger.error(f"Role remove failed for {member}: {e}")


# ──────────────────────────────────────────────────────────────
# /status HELPER  (called by the slash command cog)
# ──────────────────────────────────────────────────────────────

async def get_stream_status(user_login: str) -> dict | None:
    """
    Returns a dict with stream info if the streamer is currently live,
    or None if they are offline.

    Priority:
    1. Redis live flag (instant, set when stream goes live)
    2. Twitch API direct check via get_streams_by_logins (reliable fallback)
    """
    user_login = user_login.lower()
    status     = await redis_client.get(_status_key(user_login))

    if status == "live":
        # Already flagged live — return cached metadata
        stream = await get_cached_stream(user_login)
        if stream:
            return stream

    # No Redis flag — hit Twitch API directly to get real-time status
    try:
        from core.state_manager import state
        api = state.get_bot().app_state.twitch_api
        if api:
            live_streams = await api.get_streams_by_logins([user_login])
            if live_streams:
                s = live_streams[0]
                return {
                    "title":        s.get("title"),
                    "game_name":    s.get("game_name"),
                    "user_login":   s.get("user_login", user_login),
                    "viewer_count": s.get("viewer_count"),
                    "started_at":   s.get("started_at"),
                }
    except Exception as e:
        logger.warning(f"get_stream_status API fallback failed for {user_login}: {e}")

    return None
