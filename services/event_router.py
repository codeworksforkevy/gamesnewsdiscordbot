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

def _build_live_embed(user_login: str, user_name: str, stream: dict | None) -> discord.Embed:
    title     = stream.get("title")   if stream else f"{user_name} is live!"
    game      = stream.get("game_name") if stream else None
    # Cache-bust the thumbnail so Discord always fetches the latest frame
    thumbnail = (
        f"https://static-cdn.jtvnw.net/previews-ttv/live_user_{user_login}"
        f"-1280x720.jpg?t={int(time.time())}"
    )

    embed = discord.Embed(
        title=f"🔴  {title}",
        url=f"https://twitch.tv/{user_login}",
        color=0x9146FF,
    )

    if game:
        embed.add_field(name="Playing", value=game, inline=True)

    embed.add_field(name="Channel", value=f"[twitch.tv/{user_login}](https://twitch.tv/{user_login})", inline=True)
    embed.set_image(url=thumbnail)
    embed.set_footer(text="Live on Twitch")

    return embed


def _build_offline_embed(user_login: str, user_name: str) -> discord.Embed:
    embed = discord.Embed(
        description=f"**{user_name}** has ended their stream.",
        color=0x6e6e6e,
    )
    embed.set_footer(text=f"twitch.tv/{user_login}")
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

    # ── Fetch metadata ─────────────────────────────────────────
    stream = await get_cached_stream(user_login)
    logger.info(
        f"🟢 DEBUG event_router: stream metadata = "
        f"title={stream.get('title') if stream else None} | "
        f"game={stream.get('game_name') if stream else None}"
    )
    embed = _build_live_embed(user_login, user_name, stream)

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
                offline_embed = _build_offline_embed(user_login, user_name)
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
    1. Redis live flag (set by handle_stream_online) — instant
    2. Twitch API direct check — fallback when Redis has no flag yet
       (e.g. bot just restarted, StreamMonitor hasn't polled yet)
    """
    user_login = user_login.lower()
    status     = await redis_client.get(_status_key(user_login))

    if status == "live":
        stream = await get_cached_stream(user_login)
        return stream

    # Redis has no flag — ask Twitch API directly
    try:
        stream = await get_cached_stream(user_login)
        if stream:
            return stream
    except Exception:
        pass

    return None
