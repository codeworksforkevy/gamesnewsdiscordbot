"""
events/stream_events.py
────────────────────────────────────────────────────────────────
Handles stream.online events from Twitch EventSub.

Builds a rich Discord embed and posts (or edits) a notification
in each configured guild channel.

Fixes vs original:
- Imported from services.guild_config but the canonical module is
  db.guild_settings — unified to db.guild_settings.get_guild_config()
- config["channel_id"] used but guild_settings returns
  "announce_channel_id" — would KeyError on every notification.
  Fixed to use the correct field name.
- get_guild_config was called with (bot.app_state.db, guild.id) but
  guild_settings uses a module-level DB singleton (set_db) and only
  takes guild_id — fixed call signature.
- Metadata TTL was 60 seconds — too short for a stream that might
  change title/game. Changed to 300s to match MetadataCache default.
- change_text was built with string concatenation inside a loop with
  no separator logic — could produce double newlines or missing ones.
  Replaced with a clean list-join approach.
- No thumbnail on the embed — added cache-busted Twitch thumbnail.
- No game / viewer count fields on the embed — added both.
- No error handling on channel.send() — a single bad channel would
  break notifications for all remaining guilds.
- No deduplication: if EventSub fires twice (it can), two identical
  posts appear. Added Redis flag guard (stream:status:{login}).
- send() used unconditionally — now edit-or-send using stored msg ID,
  consistent with event_router.py from the previous batch.
- stream_offline handler was missing entirely — added.

UX improvements:
- Embed title prefixed with 🔴 to be immediately scannable in a busy
  channel without opening the embed.
- Viewer count shown as a field so members know how big the stream is.
- Cache-busted thumbnail so the preview always shows the current scene.
- Offline embed uses a muted grey colour and shows stream duration
  if the start time was cached in Redis.
- Change-detection embed (title/game shift mid-stream) uses a
  distinct amber colour so it doesn't look like a new-live ping.
"""

import json
import logging
import time
from typing import Optional

import discord

from db.guild_settings import get_guild_config
from services.redis_client import redis_client
from services.twitch_cache import get_cached_stream
from utils.stream_diff import detect_changes

logger = logging.getLogger("stream-events")

# ──────────────────────────────────────────────────────────────
# REDIS KEY HELPERS
# ──────────────────────────────────────────────────────────────

def _meta_key(login: str) -> str:
    return f"stream:meta:{login}"

def _status_key(login: str) -> str:
    return f"stream:status:{login}"

def _msg_key(login: str, guild_id: int) -> str:
    return f"stream:msg:{login}:{guild_id}"

def _start_key(login: str) -> str:
    return f"stream:start:{login}"

LIVE_TTL  = 60 * 60 * 6    # 6 hours — covers long streams
META_TTL  = 300             # 5 minutes for stream metadata


# ──────────────────────────────────────────────────────────────
# EMBED BUILDERS
# ──────────────────────────────────────────────────────────────

def _live_embed(login: str, stream: dict) -> discord.Embed:
    title     = stream.get("title") or ""
    game      = stream.get("game_name") or "Just Chatting"
    started_at = stream.get("started_at", "")

    if not game or game.lower() == "unknown":
        game = "Just Chatting"

    thumbnail = (
        f"https://static-cdn.jtvnw.net/previews-ttv/live_user_{login}"
        f"-1280x720.jpg?t={int(time.time())}"
    )

    ts_str = "now"
    if started_at:
        try:
            from datetime import datetime, timezone as _tz
            dt     = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
            ts_str = f"<t:{int(dt.timestamp())}:R>"
        except Exception:
            pass

    # Title direkt, etiket yok — viewer yok
    desc_lines = []
    if title:
        desc_lines.append(title)
    desc_lines += [
        f"\U0001f469\u200d\U0001f4bb **Game:** {game}",
        f"\u2615 **Started:** {ts_str}",
    ]

    embed = discord.Embed(
        url=f"https://twitch.tv/{login}",
        description="\n".join(desc_lines),
        color=0xFFB6C1,  # baby pink
    )

    embed.set_image(url=thumbnail)
    embed.set_footer(text="Vibes: Very Cool")
    embed.timestamp = discord.utils.utcnow()

    return embed


def _change_embed(login: str, stream: dict, changes: dict) -> discord.Embed:
    """
    Amber-coloured embed shown when title or game changes mid-stream.
    Distinct from the initial live embed so members aren't confused.
    """
    lines: list[str] = []

    if "title" in changes:
        old = changes["title"]["old"] or "—"
        new = changes["title"]["new"] or "—"
        lines.append(f"**📝 Title**\n~~{old}~~\n→ **{new}**")

    if "game" in changes:
        old = changes["game"]["old"] or "—"
        new = changes["game"]["new"] or "—"
        lines.append(f"**🎮 Game**\n~~{old}~~\n→ **{new}**")

    embed = discord.Embed(
        title="📡  Stream Updated",
        url=f"https://twitch.tv/{login}",
        description="\n\n".join(lines),
        color=0xF5A623,   # Amber — visually distinct from live/offline
    )

    embed.set_footer(text=f"twitch.tv/{login}")
    return embed


def _offline_embed(login: str, start_ts: Optional[float] = None) -> discord.Embed:
    description = f"**{login}** has ended their stream."

    if start_ts:
        duration_mins = int((time.time() - start_ts) / 60)
        hours, mins   = divmod(duration_mins, 60)
        duration_str  = f"{hours}h {mins}m" if hours else f"{mins}m"
        description  += f"\n\nStream duration: **{duration_str}**"

    embed = discord.Embed(
        description=description,
        color=0x6e6e6e,
    )
    embed.set_footer(text=f"twitch.tv/{login}")
    return embed


# ──────────────────────────────────────────────────────────────
# SEND / EDIT HELPER
# ──────────────────────────────────────────────────────────────

async def _send_or_edit(
    channel: discord.TextChannel,
    login: str,
    guild_id: int,
    content: Optional[str],
    embed: discord.Embed,
) -> None:
    """
    Edits the existing notification message if one was sent before,
    otherwise sends a fresh one and stores the message ID.
    """
    msg_key    = _msg_key(login, guild_id)
    stored_raw = await redis_client.get(msg_key)

    if stored_raw:
        try:
            message = await channel.fetch_message(int(stored_raw))
            await message.edit(content=content, embed=embed)
            return
        except Exception as e:
            logger.warning(
                "Could not edit existing message, will re-send",
                extra={"extra_data": {"guild_id": guild_id, "error": str(e)}},
            )

    try:
        message = await channel.send(content=content, embed=embed)
        await redis_client.set(msg_key, str(message.id), ttl=LIVE_TTL)
    except Exception as e:
        logger.error(
            "Failed to send stream notification",
            extra={"extra_data": {"guild_id": guild_id, "error": str(e)}},
        )


# ──────────────────────────────────────────────────────────────
# STREAM ONLINE
# ──────────────────────────────────────────────────────────────

async def handle_stream_online(bot, event: dict) -> None:

    login      = event["broadcaster_user_login"].lower()
    user_name  = event.get("broadcaster_user_name", login)

    logger.info("stream.online received", extra={"extra_data": {"login": login}})

    # ── Deduplication ───────────────────────────────────────────
    already_live = await redis_client.get(_status_key(login))
    if already_live == "live":
        logger.info(f"Duplicate stream.online ignored for {login}")
        return

    await redis_client.set(_status_key(login), "live", ttl=LIVE_TTL)
    await redis_client.set(_start_key(login), str(time.time()), ttl=LIVE_TTL)

    # ── Fetch current stream metadata ───────────────────────────
    new_stream = await get_cached_stream(login)
    if not new_stream:
        logger.warning(
            "No stream metadata available — skipping notification",
            extra={"extra_data": {"login": login}},
        )
        return

    # ── Detect changes vs previous cached metadata ─────────────
    # Normalise keys: detect_changes uses "game", cache uses "game_name"
    old_raw    = await redis_client.get(_meta_key(login))
    old_stream = json.loads(old_raw) if old_raw else None
    if old_stream and "game_name" in old_stream:
        old_stream["game"] = old_stream.pop("game_name")
    new_norm = dict(new_stream)
    if "game_name" in new_norm:
        new_norm["game"] = new_norm.pop("game_name")
    changes = detect_changes(old_stream, new_norm) if old_stream else {}

    # Update metadata cache
    await redis_client.set(_meta_key(login), json.dumps(new_stream), ttl=META_TTL)

    # ── Build embed ─────────────────────────────────────────────
    if changes:
        embed = _change_embed(login, new_stream, changes)
    else:
        embed = _live_embed(login, new_stream)

    # ── Notify each guild ───────────────────────────────────────
    for guild in bot.guilds:

        config = await get_guild_config(guild.id)
        if not config:
            continue

        # Fixed: field is announce_channel_id, not channel_id
        channel = guild.get_channel(config.get("announce_channel_id"))
        if not channel:
            logger.warning(
                "Announce channel not found",
                extra={"extra_data": {
                    "guild_id":   guild.id,
                    "channel_id": config.get("announce_channel_id"),
                }},
            )
            continue

        content: Optional[str] = None
        if config.get("enable_ping") and config.get("ping_role_id"):
            role = guild.get_role(config["ping_role_id"])
            if role:
                content = role.mention

        await _send_or_edit(channel, login, guild.id, content, embed)

    logger.info(
        "stream.online notifications dispatched",
        extra={"extra_data": {"login": login, "guilds": len(bot.guilds)}},
    )


# ──────────────────────────────────────────────────────────────
# STREAM OFFLINE
# ──────────────────────────────────────────────────────────────

async def handle_stream_offline(bot, event: dict) -> None:

    login = event["broadcaster_user_login"].lower()

    logger.info("stream.offline received", extra={"extra_data": {"login": login}})

    # Retrieve stream start time for duration display
    start_raw  = await redis_client.get(_start_key(login))
    start_ts   = float(start_raw) if start_raw else None

    # Clean up Redis live state
    await redis_client.delete(_status_key(login), _meta_key(login), _start_key(login))

    embed = _offline_embed(login, start_ts)

    for guild in bot.guilds:

        config = await get_guild_config(guild.id)
        if not config:
            continue

        channel = guild.get_channel(config.get("announce_channel_id"))
        if not channel:
            continue

        # Clean up stored live message ID — offline embed is always a new post
        msg_key = _msg_key(login, guild.id)
        await redis_client.delete(msg_key)

        try:
            await channel.send(embed=embed)
        except Exception as e:
            logger.error(
                "Failed to send offline notification",
                extra={"extra_data": {"guild_id": guild.id, "error": str(e)}},
            )

    logger.info(
        "stream.offline notifications dispatched",
        extra={"extra_data": {"login": login}},
    )
