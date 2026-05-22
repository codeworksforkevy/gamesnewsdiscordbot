"""
events/stream_events.py
────────────────────────────────────────────────────────────────
Verwerkt alle Twitch EventSub-events (online, offline, channel.update).
Samenvoegde community-routing, API-vertragingsfallbacks en DB-synchronisatie.
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
# CONSTANTEN & ROUTING
# ──────────────────────────────────────────────────────────────

LIVE_TTL  = 60 * 60 * 6    # 6 uur — actieve livestream-cache
META_TTL  = 300             # 5 minuten — stroommetadata voor wijzigingsdetectie

# Kleurenpalet — consistent met Find a Curie-embeds
COLOR_LIVE    = 0xFFB6C1   # Babyroos — live-aankondiging
COLOR_UPDATE  = 0xF5A623   # Amber — stream-updates
COLOR_OFFLINE = 0x1C1C2E   # Donker marineblauw — offline-embed

KEVKEVVY_LOGIN      = "kevkevvy"
KEVKEVVY_CHANNEL_ID = 1446562544612540645

# Redis-sleutelhulpfuncties
def _meta_key(login: str) -> str:    return f"stream:meta:{login}"
def _status_key(login: str) -> str:  return f"stream:status:{login}"
def _msg_key(login: str, guild_id: int) -> str: return f"stream:msg:{login}:{guild_id}"
def _start_key(login: str) -> str:   return f"stream:start:{login}"


def _get_target_channel(guild: discord.Guild, config: dict, login: str) -> Optional[discord.TextChannel]:
    """Geeft het juiste aankondigingskanaal terug op basis van streamer-login."""
    if login == KEVKEVVY_LOGIN:
        ch = guild.get_channel(KEVKEVVY_CHANNEL_ID)
        if ch:
            return ch
    ch_id = config.get("announce_channel_id")
    return guild.get_channel(ch_id) if ch_id else None


# ──────────────────────────────────────────────────────────────
# EMBED-BOUWERS
# ──────────────────────────────────────────────────────────────

def _live_embed(login: str, user_name: str, stream: dict) -> discord.Embed:
    """Babyroos live-aankondigings-embed — stijl conform Find a Curie."""
    title     = stream.get("title") or "Geen titel opgegeven"
    game      = stream.get("game_name") or "Just Chatting"
    started_at = stream.get("started_at", "")

    # Thumbnail met cache-busting voor live voorbeeld
    thumbnail = (
        f"https://static-cdn.jtvnw.net/previews-ttv/live_user_{login}-1280x720.jpg"
        f"?t={int(time.time())}"
    )

    # Relatieve timestamp
    ts_str = "zonet"
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
    embed.add_field(name="🎮 Spel",       value=game,   inline=True)
    embed.add_field(name="⏱️ Gestart",   value=ts_str, inline=True)
    embed.set_image(url=thumbnail)
    embed.set_footer(text=f"twitch.tv/{login}")
    embed.timestamp = discord.utils.utcnow()
    return embed


def _change_embed(login: str, user_name: str, changes: dict) -> discord.Embed:
    """Amber-embed voor stream-updates (titelwijziging of spelwisseling)."""
    embed = discord.Embed(
        title="📡 Stream bijgewerkt",
        url=f"https://twitch.tv/{login}",
        color=COLOR_UPDATE,
    )
    embed.set_author(
        name=user_name,
        url=f"https://twitch.tv/{login}",
    )
    if "title" in changes:
        embed.add_field(
            name="📝 Titel",
            value=f"~~{changes['title']['old']}~~\n→ **{changes['title']['new']}**",
            inline=False,
        )
    if "game" in changes:
        embed.add_field(
            name="🎮 Spel",
            value=f"~~{changes['game']['old']}~~\n→ **{changes['game']['new']}**",
            inline=False,
        )
    embed.set_footer(text=f"twitch.tv/{login}")
    embed.timestamp = discord.utils.utcnow()
    return embed


def _offline_embed(login: str, user_name: str, start_ts: Optional[float]) -> discord.Embed:
    """Donker marineblauw offline-embed — stijl conform Find a Curie."""
    desc = f"**{user_name}** heeft de stream beëindigd."
    if start_ts:
        mins  = int((time.time() - start_ts) / 60)
        uren  = mins // 60
        rest  = mins % 60
        desc += f"\n\n🕐 Streamduur: **{uren}u {rest}m**"

    embed = discord.Embed(description=desc, color=COLOR_OFFLINE)
    embed.set_author(
        name=user_name,
        url=f"https://twitch.tv/{login}",
    )
    embed.set_footer(text=f"twitch.tv/{login}")
    embed.timestamp = discord.utils.utcnow()
    return embed


# ──────────────────────────────────────────────────────────────
# HULPFUNCTIE — BERICHT VERZENDEN OF BEWERKEN
# ──────────────────────────────────────────────────────────────

async def _send_or_edit(
    channel: discord.TextChannel,
    login: str,
    guild_id: int,
    content: Optional[str],
    embed: discord.Embed,
) -> None:
    """
    Bewerkt het bestaande live-bericht als het nog bestaat in Redis,
    anders wordt er een nieuw bericht geplaatst.
    """
    msg_key = _msg_key(login, guild_id)
    stored  = await redis_client.get(msg_key)
    if stored:
        try:
            msg = await channel.fetch_message(int(stored))
            await msg.edit(content=content, embed=embed)
            return
        except Exception:
            pass  # Bericht verwijderd of niet meer bereikbaar — stuur nieuw
    msg = await channel.send(content=content, embed=embed)
    await redis_client.set(msg_key, str(msg.id), ttl=LIVE_TTL)


# ──────────────────────────────────────────────────────────────
# EVENT-HANDLERS
# ──────────────────────────────────────────────────────────────

async def handle_stream_online(bot, event: dict) -> None:
    """
    Verwerkt stream.online-event.
    Gebruikt het unieke stream-ID van Twitch om dubbele meldingen te voorkomen.
    """
    login      = event["broadcaster_user_login"].lower()
    user_name  = event.get("broadcaster_user_name", login)
    b_id       = event.get("broadcaster_user_id")
    stream_id  = event.get("id", "live")  # Uniek Twitch-stream-ID — voorkomt spooksloten

    # Sla op als hetzelfde stream-ID al actief is
    already_live_id = await redis_client.get(_status_key(login))
    if already_live_id == stream_id:
        logger.info(f"Dubbel stream.online genegeerd voor {login} (zelfde stream_id)")
        return

    await redis_client.set(_status_key(login), stream_id,         ttl=LIVE_TTL)
    await redis_client.set(_start_key(login),  str(time.time()),  ttl=LIVE_TTL)

    # Twitch API heeft soms een korte vertraging na het online-event
    new_stream = await get_cached_stream(login)
    if not new_stream:
        await asyncio.sleep(10)
        new_stream = await get_cached_stream(login)

    # Fallback als API nog niet reageert
    if not new_stream:
        new_stream = {"title": "Live!", "game_name": "Onbekend"}

    # Stuur aankondiging naar alle relevante servers
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
    Verwerkt stream.offline-event.
    Stuurt donkere offline-embed en ruimt Redis-sleutels op.
    """
    login     = event["broadcaster_user_login"].lower()
    user_name = event.get("broadcaster_user_name", login)
    b_id      = event.get("broadcaster_user_id")

    if b_id:
        await set_stream_offline(b_id)

    # Haal starttijd op vóór verwijdering
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
    Verwerkt channel.update-event.
    Stuurt alleen een embed als er een echte wijziging is en de stream actief is.
    """
    login     = event["broadcaster_user_login"].lower()
    user_name = event.get("broadcaster_user_name", login)

    # Negeer updates als de streamer momenteel offline is
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
