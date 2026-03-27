# services/luna_poster.py
#
# Background task that polls Prime Gaming / Luna+ every 6 hours.
# When new games are detected it posts rich embeds to every guild's
# announce channel automatically.
#
# Also used by the /membership_exclusives slash command directly.

import asyncio
import json
import logging
from typing import List, Dict, Any

import discord

from services.luna import fetch_luna_membership
from services.diff_engine import diff_games
from config import PLATFORM_COLORS, LUNA_UPDATE_INTERVAL
from db.guild_settings import get_guild_config

logger = logging.getLogger("luna-poster")

CACHE_KEY = "luna_games_cache"
_memory_cache: List[Dict] = []


# ==================================================
# EMBED BUILDER
# UX: shows end date if available, clean bullet layout
# ==================================================

def build_luna_embed(games: List[Dict[str, Any]]) -> discord.Embed:
    """
    Build a single embed showing all new Luna/Prime Gaming games.
    Groups them into one clean embed rather than spamming one per game.
    """
    embed = discord.Embed(
        title="🎮 New Free Games on Prime Gaming!",
        description=(
            "New games are available free with your Prime membership.\n"
            "Claim them at [gaming.amazon.com](https://gaming.amazon.com/home)"
        ),
        color=PLATFORM_COLORS.get("luna", 0x00A8E1),
        url="https://gaming.amazon.com/home",
    )

    for game in games[:10]:   # Discord embed field limit safety
        title     = game.get("title", "Unknown Game")
        end_time  = game.get("end_time", "")
        desc      = game.get("description", "Free with Prime Gaming")
        thumbnail = game.get("thumbnail", "")

        value = desc
        if end_time:
            # Format: "Ends <t:TIMESTAMP:R>" → Discord relative timestamp
            try:
                from datetime import datetime
                dt = datetime.fromisoformat(end_time.replace("Z", "+00:00"))
                ts = int(dt.timestamp())
                value += f"\n⏰ Ends <t:{ts}:R>"
            except Exception:
                pass

        embed.add_field(name=f"🕹️ {title}", value=value, inline=False)

        # Set the first game's thumbnail as the embed image
        if thumbnail and not embed.image.url:
            embed.set_image(url=thumbnail)

    embed.set_footer(
        text=f"Prime Gaming • {len(games)} new game{'s' if len(games) != 1 else ''}"
    )

    return embed


# ==================================================
# CACHE HELPERS
# ==================================================

async def _get_cached(redis=None) -> List[Dict]:
    global _memory_cache

    if not redis:
        return _memory_cache

    try:
        raw = await redis.get(CACHE_KEY)
        if not raw:
            return _memory_cache
        if isinstance(raw, bytes):
            raw = raw.decode()
        data = json.loads(raw)
        _memory_cache = data
        return data
    except Exception as e:
        logger.warning(f"Luna cache read failed: {e}")
        return _memory_cache


async def _set_cached(games: List[Dict], redis=None) -> None:
    global _memory_cache
    _memory_cache = games

    if redis:
        try:
            await redis.set(CACHE_KEY, json.dumps(games))
        except Exception as e:
            logger.warning(f"Luna cache write failed: {e}")


# ==================================================
# NOTIFIER
# Posts embeds to all guilds that have an announce channel set
# ==================================================

async def _notify_guilds(bot: discord.Client, new_games: List[Dict]) -> None:

    if not new_games:
        return

    embed = build_luna_embed(new_games)

    for guild in bot.guilds:
        try:
            config = await get_guild_config(guild.id)
            if not config:
                continue

           channel_id = config.get("games_channel_id") or config.get("announce_channel_id")
            if not channel_id:
                continue

            channel = (
                guild.get_channel(channel_id)
                or await bot.fetch_channel(channel_id)
            )
            if not channel:
                continue

            await channel.send(embed=embed)
            logger.info(f"Luna: posted {len(new_games)} new games to {guild.name}")

        except discord.Forbidden:
            logger.warning(f"Luna: no permission to post in guild {guild.id}")
        except Exception as e:
            logger.error(f"Luna: failed to post to guild {guild.id}: {e}")


# ==================================================
# MAIN UPDATE LOOP
# ==================================================

async def update_luna_cache(bot: discord.Client, session, redis=None) -> None:
    """
    Fetch, diff, and notify. Called by the background loop and can also
    be called manually to force a refresh.
    """
    logger.info("Luna: fetching games...")

    try:
        new_games = await fetch_luna_membership(session)
    except Exception as e:
        logger.error(f"Luna fetch error: {e}")
        return

    if not new_games:
        logger.warning("Luna: fetch returned empty — skipping diff")
        return

    old_games = await _get_cached(redis)
    new_only  = diff_games(old_games, new_games)

    await _set_cached(new_games, redis)

    if not new_only:
        logger.info("Luna: no new games detected")
        return

    logger.info(f"Luna: {len(new_only)} new game(s) detected — notifying guilds")
    await _notify_guilds(bot, new_only)


async def luna_poster_loop(bot: discord.Client, session, redis=None) -> None:
    """
    Background task. Starts after bot is ready, polls every 6 hours.
    Add to main.py:
        asyncio.create_task(luna_poster_loop(bot, session, cache))
    """
    await bot.wait_until_ready()
    logger.info("Luna poster loop started")

    ERROR_BASE = 60    # seconds
    ERROR_MAX  = 600   # 10 min cap
    error_count = 0

    while True:
        try:
            await update_luna_cache(bot, session, redis)
            error_count = 0
            await asyncio.sleep(LUNA_UPDATE_INTERVAL)

        except asyncio.CancelledError:
            logger.info("Luna poster loop cancelled")
            break
        except Exception as e:
            error_count += 1
            backoff = min(ERROR_BASE * (2 ** (error_count - 1)), ERROR_MAX)
            logger.error(f"Luna loop error: {e} — retrying in {backoff}s")
            await asyncio.sleep(backoff)
