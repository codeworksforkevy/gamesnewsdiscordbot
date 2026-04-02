import time
import json
import logging
import asyncio
import discord
from datetime import datetime, timezone

from db.guild_settings import get_guild_config
from services.redis_client import redis_client
from services.twitch_cache import get_cached_stream

logger = logging.getLogger("event_router")

# ──────────────────────────────────────────────────────────────
# CONSTANTS
# ──────────────────────────────────────────────────────────────

LIVE_TTL = 60 * 60 * 6   # 6 hours

# KevKevvy's own stream goes to her dedicated channel
KEVKEVVY_LOGIN      = "kevkevvy"
KEVKEVVY_CHANNEL_ID = 1446562544612540645   # her personal stream channel

# Friends' streams go to the friends-streams channel (announce_channel_id)
# No viewer count shown in friends-streams posts

# ──────────────────────────────────────────────────────────────
# REDIS HELPERS
# ──────────────────────────────────────────────────────────────

def _status_key(user_login: str) -> str:
    return f"stream:status:{user_login.lower()}"

def _msg_key(user_login: str, guild_id: int) -> str:
    return f"stream:msg:{user_login.lower()}:{guild_id}"

def _format_duration(seconds: int) -> str:
    h, rem = divmod(int(seconds), 3600)
    m, s   = divmod(rem, 60)
    return f"{h}h {m}m {s}s" if h else f"{m}m {s}s"

# ──────────────────────────────────────────────────────────────
# EMBED BUILDERS
# ──────────────────────────────────────────────────────────────

def _build_live_embed(
    user_login: str,
    user_name:  str,
    stream:     dict | None,
    user_info:  dict | None = None,
    show_viewers: bool = False,   # viewer count hidden by default
) -> discord.Embed:
    title      = (stream.get("title") if stream else None) or "No Title"
    game       = (stream.get("game_name") if stream else None) or "Creative / Art"
    started_at = stream.get("started_at", "") if stream else ""

    if not game or game.lower() == "unknown":
        game = "Creative / Art"

    stream_url = f"https://www.twitch.tv/{user_login}"

    ts_str = "now"
    if started_at:
        try:
            dt     = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
            ts_str = f"<t:{int(dt.timestamp())}:R>"
        except Exception:
            pass

    # Description — no viewer count for friends-streams
    desc_lines = [
        f"👩‍🔬 **Project:** {title}",
        f"👩‍💻 **Game:** `{game}`",
        f"☕ **Started:** {ts_str}",
    ]
    if show_viewers and stream and stream.get("viewer_count"):
        desc_lines.insert(2, f"👥 **Viewers:** {stream['viewer_count']:,}")

    embed = discord.Embed(
        title=f"🎬 {title}",
        url=stream_url,
        description="\n".join(desc_lines),
        color=0xFFB6C1,  # Kevy pink
    )

    icon_url = user_info.get("profile_image_url") if user_info else None
    embed.set_author(name=user_name, url=stream_url, icon_url=icon_url)

    raw_thumb = stream.get("thumbnail_url", "") if stream else ""
    if raw_thumb:
        thumb = raw_thumb.replace("{width}", "1280").replace("{height}", "720")
        embed.set_image(url=f"{thumb}?v={int(time.time())}")

    embed.set_footer(text="🧪 Atmosphere: Very Cool")
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
    Matches the screenshot style:
    - Author line: profile pic + "<name> was live on Twitch"
    - Description: italic stream title
    - Fields (inline): Game | Duration | VOD
    - Footer: "Stream ended • twitch.tv/<login>"
    - Dark background colour
    """
    stream_url = f"https://twitch.tv/{user_login}"
    title_text = (stream_info.get("title") if stream_info else None) or "No Title"
    game       = (stream_info.get("game_name") if stream_info else None) or "Creative / Art"

    embed = discord.Embed(
        description=f"*{title_text}*",
        color=0x2f3136,
    )

    # Author with profile picture — "<name> was live on Twitch"
    icon_url = user_info.get("profile_image_url") if user_info else None
    embed.set_author(
        name=f"{user_name} was live on Twitch",
        url=stream_url,
        icon_url=icon_url,
    )

    # Three inline fields: Game | Duration | VOD
    embed.add_field(name="🎮 Game",      value=game,                                     inline=True)
    embed.add_field(name="🕐 Duration",  value=duration or "Unknown",                    inline=True)
    embed.add_field(
        name="📹 VOD",
        value=f"[Click to watch]({vod_url})" if vod_url
              else f"[Videos](https://www.twitch.tv/{user_login}/videos)",
        inline=True,
    )

    # Footer: "Stream ended • twitch.tv/<login>"
    embed.set_footer(text=f"Stream ended • twitch.tv/{user_login}")
    embed.timestamp = datetime.now(timezone.utc)
    return embed


# ──────────────────────────────────────────────────────────────
# /status HELPER
# ──────────────────────────────────────────────────────────────

async def get_stream_status(user_login: str) -> dict | None:
    user_login = user_login.lower()
    status     = await redis_client.get(_status_key(user_login))

    if status == "live":
        stream = await get_cached_stream(user_login)
        if stream:
            return stream

    # Redis empty — hit Twitch API directly
    try:
        from core.state_manager import state
        api = state.get_bot().app_state.twitch_api
        if api:
            results = await api.get_streams_by_logins([user_login])
            if results:
                return results[0]
    except Exception as e:
        logger.warning(f"get_stream_status API fallback failed for {user_login}: {e}")

    return None


# ──────────────────────────────────────────────────────────────
# STREAM ONLINE
# ──────────────────────────────────────────────────────────────

async def handle_stream_online(bot, event: dict) -> None:
    user_login = event.get("broadcaster_user_login", "").lower()
    user_name  = event.get("broadcaster_user_name", user_login)

    if not user_login:
        logger.error("🔴 EventSub payload missing broadcaster_user_login")
        return

    logger.info(f"🚀 handle_stream_online: {user_login}")

    # Deduplication
    existing = await redis_client.get(_status_key(user_login))
    if existing == "live":
        logger.info(f"⚪ Duplicate online event — skipping {user_login}")
        return

    await redis_client.set(_status_key(user_login), "live", ttl=LIVE_TTL)

    # Fetch stream metadata + user profile
    stream    = None
    user_info = None
    try:
        api = bot.app_state.twitch_api
        if api:
            results   = await api.get_streams_by_logins([user_login])
            stream    = results[0] if results else None
            user_info = await api.get_user_by_login(user_login)
    except Exception as e:
        logger.warning(f"Metadata fetch failed for {user_login}: {e}")

    # Store for offline embed
    if stream:
        try:
            await redis_client.set(
                f"stream:last:{user_login}",
                json.dumps({
                    "title":      stream.get("title"),
                    "game_name":  stream.get("game_name"),
                    "started_at": stream.get("started_at"),
                }),
                ttl=LIVE_TTL,
            )
        except Exception:
            pass

    # Per-guild posting
    for guild in bot.guilds:
        try:
            # KevKevvy gets her own dedicated channel
            if user_login == KEVKEVVY_LOGIN:
                channel_id   = KEVKEVVY_CHANNEL_ID
                show_viewers = False  # viewer count hidden everywhere
            else:
                config = await get_guild_config(guild.id)
                if not config:
                    continue
                channel_id   = config.get("announce_channel_id")
                show_viewers = False  # no viewer count in friends-streams

            if not channel_id:
                continue

            channel = guild.get_channel(channel_id) or await bot.fetch_channel(channel_id)
            if not channel:
                logger.warning(f"Channel {channel_id} not found in {guild.name}")
                continue

            embed = _build_live_embed(
                user_login, user_name, stream, user_info,
                show_viewers=show_viewers,
            )

            live_role = discord.utils.get(guild.roles, name="🔴 Live")
            content   = live_role.mention if live_role else None

            msg = await channel.send(content=content, embed=embed)
            await redis_client.set(_msg_key(user_login, guild.id), str(msg.id), ttl=LIVE_TTL)
            logger.info(f"✅ Posted live notification for {user_login} in {guild.name} → #{channel}")

        except Exception as e:
            logger.error(f"🔴 Post failed for {user_login} in guild {guild.id}: {e}")


# ──────────────────────────────────────────────────────────────
# STREAM OFFLINE
# ──────────────────────────────────────────────────────────────

async def handle_stream_offline(bot, event: dict) -> None:
    user_login = event.get("broadcaster_user_login", "").lower()
    user_name  = event.get("broadcaster_user_name", user_login)

    logger.info(f"⚫ handle_stream_offline: {user_login}")

    await redis_client.delete(_status_key(user_login))

    # Fetch last stream info + VOD
    stream_info = None
    user_info   = None
    vod_url     = None
    duration    = None

    try:
        raw = await redis_client.get(f"stream:last:{user_login}")
        if raw:
            stream_info = json.loads(raw)
            if stream_info.get("started_at"):
                start = datetime.fromisoformat(
                    stream_info["started_at"].replace("Z", "+00:00")
                )
                elapsed  = (datetime.now(timezone.utc) - start).total_seconds()
                duration = _format_duration(elapsed)
    except Exception:
        pass

    try:
        api = bot.app_state.twitch_api
        if api:
            user_info = await api.get_user_by_login(user_login)
            if user_info:
                vod_data = await api.request(
                    "videos",
                    params={"user_id": user_info["id"], "type": "archive", "first": 1}
                )
                if vod_data and vod_data.get("data"):
                    vod_url = vod_data["data"][0].get("url")
    except Exception as e:
        logger.warning(f"VOD fetch failed for {user_login}: {e}")

    offline_embed = _build_offline_embed(
        user_login, user_name,
        stream_info=stream_info,
        vod_url=vod_url,
        duration=duration,
        user_info=user_info,
    )

    for guild in bot.guilds:
        try:
            # Determine channel same way as online
            if user_login == KEVKEVVY_LOGIN:
                channel_id = KEVKEVVY_CHANNEL_ID
            else:
                config = await get_guild_config(guild.id)
                if not config:
                    continue
                channel_id = config.get("announce_channel_id")

            if not channel_id:
                continue

            # Try to edit the live message first
            msg_id_str = await redis_client.get(_msg_key(user_login, guild.id))
            if msg_id_str:
                try:
                    channel = guild.get_channel(channel_id) or await bot.fetch_channel(channel_id)
                    msg     = await channel.fetch_message(int(msg_id_str))
                    await msg.edit(content=None, embed=offline_embed)
                    logger.info(f"✅ Edited live→offline for {user_login} in {guild.name}")
                except discord.NotFound:
                    pass
                except Exception as e:
                    logger.warning(f"Could not edit message: {e}")
            else:
                # No stored message — send fresh offline post
                channel = guild.get_channel(channel_id) or await bot.fetch_channel(channel_id)
                if channel:
                    await channel.send(embed=offline_embed)

            await redis_client.delete(_msg_key(user_login, guild.id))

        except Exception as e:
            logger.error(f"🔴 Offline post failed for {user_login} in {guild.id}: {e}")
