import time
import logging
import discord
from datetime import datetime, timezone

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

LIVE_TTL = 60 * 60 * 6  # 6 saat

# ──────────────────────────────────────────────────────────────
# FORMATTERS
# ──────────────────────────────────────────────────────────────

def _format_duration(seconds: int) -> str:
    h, rem = divmod(int(seconds), 3600)
    m, s   = divmod(rem, 60)
    return f"{h}h {m}m {s}s" if h else f"{m}m {s}s"

# ──────────────────────────────────────────────────────────────
# KEVY STYLE EMBED BUILDER (YENİ TASARIM)
# ──────────────────────────────────────────────────────────────

def _build_live_embed(
    user_login: str,
    user_name:  str,
    stream:     dict | None,
    user_info:  dict | None = None,
) -> discord.Embed:
    # Verileri güvenli çek
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
            ts = int(dt.timestamp())
            ts_str = f"<t:{ts}:R>"
        except: pass

    # VIEWERS TAMAMEN KALDIRILDI - KEVY STİLİ AÇIKLAMA
    description = (
        f"🏋️🏋️ **Time to chill with Kevy!** 🏋️🏋️\n\n"
        f"Grab your pencils, the art class is starting! ✏️\n\n"
        f"👩‍🔬 **Project:** {title}\n"
        f"👩‍💻 **Game:** `{game}`\n"
        f"☕ **Started:** {ts_str}"
    )

    embed = discord.Embed(
        title=f"🎬 {title}",
        url=stream_url,
        description=description,
        color=0xFFB6C1, 
    )

    # Author
    icon_url = user_info.get("profile_image_url") if user_info else None
    embed.set_author(name=user_name, url=stream_url, icon_url=icon_url)

    # Thumbnail (Cache-buster ile)
    raw_thumb = stream.get("thumbnail_url", "") if stream else ""
    if raw_thumb:
        thumbnail = raw_thumb.replace("{width}", "1280").replace("{height}", "720")
        thumbnail += f"?v={int(time.time())}"
        embed.set_image(url=thumbnail)

    embed.set_footer(text="🧪 Atmosphere: Very Cool")
    embed.timestamp = discord.utils.utcnow()
    return embed


def _build_offline_embed(
    user_login: str,
    user_name:  str,
    stream:     dict | None,
) -> discord.Embed:
    now = datetime.now(timezone.utc)
    duration_str = "Unknown"
    
    if stream and stream.get("started_at"):
        try:
            start_dt = datetime.fromisoformat(stream["started_at"].replace("Z", "+00:00"))
            diff = now - start_dt
            duration_str = _format_duration(diff.total_seconds())
        except: pass

    game = stream.get("game_name") or stream.get("game") or "Creative / Art"

    embed = discord.Embed(
        title=f"{user_name} was live on Twitch",
        url=f"https://twitch.tv/{user_login}",
        description=f"*{stream.get('title', 'No title')}*", # ITALIC BAŞLIK
        color=0x2f3136,
    )

    # 3 Sütunlu yapı (Viewers yok)
    embed.add_field(name="👩‍💻 Game", value=game, inline=True)
    embed.add_field(name="⏱️ Duration", value=duration_str, inline=True)
    embed.add_field(name="🎬 VOD", value=f"[Click to watch](https://twitch.tv/{user_login}/videos)", inline=True)

    embed.set_footer(text=f"⚫ Stream ended • twitch.tv/{user_login}")
    embed.timestamp = now
    return embed

# ──────────────────────────────────────────────────────────────
# HANDLERS
# ──────────────────────────────────────────────────────────────

async def handle_stream_online(bot, event: dict) -> None:
    user_login = event["broadcaster_user_login"].lower()
    user_name  = event["broadcaster_user_name"]
    
    # Redis'e canlı bilgisini işle
    await redis_client.set(_status_key(user_login), "live", expire=LIVE_TTL)
    
    # Twitch'ten detaylı stream verisini çek (Title, Game vb. için)
    stream = None
    try:
        api = bot.app_state.twitch_api
        live_streams = await api.get_streams_by_logins([user_login])
        if live_streams:
            stream = live_streams[0]
            # Metadata'yı Redis'te önbellekle (edit'ler için)
            from services.twitch_cache import cache_stream
            await cache_stream(user_login, stream)
    except Exception as e:
        logger.error(f"Failed to fetch stream details: {e}")

    # Tüm sunucularda duyuru yap
    for guild in bot.guilds:
        try:
            # 1. Bu yayıncıya özel kanal var mı bak (streamers tablosundan)
            row = await bot.app_state.db.fetchrow(
                "SELECT target_channel_id FROM streamers WHERE twitch_login = $1 AND guild_id = $2", 
                user_login, guild.id
            )
            
            channel_id = row["target_channel_id"] if row and row["target_channel_id"] else None
            
            # 2. Yoksa varsayılan kanalı al
            if not channel_id:
                config = await get_guild_config(guild.id)
                channel_id = config.get("announce_channel_id") if config else None

            if not channel_id: continue

            channel = guild.get_channel(channel_id) or await bot.fetch_channel(channel_id)
            if not channel: continue

            user_info = await bot.app_state.twitch_api.get_user_by_login(user_login)
            embed = _build_live_embed(user_login, user_name, stream, user_info)
            
            # Live role mention
            live_role = discord.utils.get(guild.roles, name="Live")
            content = live_role.mention if live_role else None
            
            msg = await channel.send(content=content, embed=embed)
            
            # Mesaj ID'sini Redis'e kaydet (Offline'da editlemek için)
            await redis_client.set(_msg_key(user_login, guild.id), str(msg.id), expire=LIVE_TTL)

        except Exception as e:
            logger.error(f"Error posting online for {user_login} in {guild.name}: {e}")


async def handle_stream_offline(bot, event: dict) -> None:
    user_login = event["broadcaster_user_login"].lower()
    user_name  = event["broadcaster_user_name"]
    
    # Canlılık durumunu sil
    await redis_client.delete(_status_key(user_login))
    
    # Son stream verisini al (Başlık vb. için)
    stream = await get_cached_stream(user_login)

    for guild in bot.guilds:
        try:
            msg_id = await redis_client.get(_msg_key(user_login, guild.id))
            if not msg_id: continue

            # Kanalı bul
            row = await bot.app_state.db.fetchrow(
                "SELECT target_channel_id FROM streamers WHERE twitch_login = $1 AND guild_id = $2", 
                user_login, guild.id
            )
            channel_id = row["target_channel_id"] if row and row["target_channel_id"] else None
            if not channel_id:
                config = await get_guild_config(guild.id)
                channel_id = config.get("announce_channel_id") if config else None

            channel = guild.get_channel(channel_id) or await bot.fetch_channel(channel_id)
            if not channel: continue

            msg = await channel.fetch_message(int(msg_id))
            if msg:
                await msg.edit(embed=_build_offline_embed(user_login, user_name, stream))
            
            await redis_client.delete(_msg_key(user_login, guild.id))

        except Exception as e:
            logger.debug(f"Offline edit failed for {user_login} in {guild.name}: {e}")
