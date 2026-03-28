# services/steam_poster.py
#
# Background task that polls Steam's featured deals every 2 hours.
# Only posts deals above STEAM_MIN_DISCOUNT threshold to avoid spam.
# Also used by the /game_discounts slash command.

import asyncio
import json
import logging
from typing import List, Dict, Any

import discord

from services.steam import fetch_steam_discounts
from services.diff_engine import diff_games
from constants import PLATFORM_COLORS, STEAM_UPDATE_INTERVAL, STEAM_MIN_DISCOUNT
from db.guild_settings import get_guild_config

logger = logging.getLogger("steam-poster")

CACHE_KEY = "steam_deals_cache"
_memory_cache: List[Dict] = []


# ==================================================
# EMBED BUILDER
# UX: paginated would be nicer but auto-posts need
# a single clean embed. Slash command handles pagination.
# ==================================================

def build_steam_embed(games: List[Dict[str, Any]]) -> discord.Embed:
    """
    Build a single embed for the top Steam deals.
    Shows up to 8 deals (Discord field limit is 25 but 8 keeps it readable).
    """
    embed = discord.Embed(
        title="🔥 Steam Deals Alert!",
        description=(
            f"New deals with **{STEAM_MIN_DISCOUNT}%+ discount** on Steam.\n"
            f"[Browse all deals](https://store.steampowered.com/specials)"
        ),
        color=PLATFORM_COLORS.get("steam", 0x1B2838),
        url="https://store.steampowered.com/specials",
    )

    # Show top 8 by discount (already sorted by steam.py)
    for game in games[:8]:
        name          = game.get("name", "Unknown Game")
        discount      = game.get("discount", 0)
        final_price   = game.get("final_price", "?")
        original_price= game.get("original_price", "?")
        url           = game.get("url", "https://store.steampowered.com")

        value = (
            f"🔖 **-{discount}%** — ~~{original_price}~~ → **{final_price}**\n"
            f"[View on Steam]({url})"
        )

        embed.add_field(name=f"🎮 {name}", value=value, inline=False)

    # Use thumbnail of the top deal
    first_thumb = games[0].get("thumbnail", "") if games else ""
    if first_thumb:
        embed.set_image(url=first_thumb)

    embed.set_footer(
        text=f"Steam • {len(games)} deal{'s' if len(games) != 1 else ''} found"
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
        logger.warning(f"Steam cache read failed: {e}")
        return _memory_cache


async def _set_cached(games: List[Dict], redis=None) -> None:
    global _memory_cache
    _memory_cache = games

    if redis:
        try:
            await redis.set(CACHE_KEY, json.dumps(games))
        except Exception as e:
            logger.warning(f"Steam cache write failed: {e}")


# ==================================================
# NOTIFIER
# ==================================================

async def _notify_guilds(bot: discord.Client, new_games: List[Dict]) -> None:

    if not new_games:
        return

    # Only notify if there are deals above the threshold
    qualifying = [g for g in new_games if g.get("discount", 0) >= STEAM_MIN_DISCOUNT]

    if not qualifying:
        logger.info("Steam: new deals found but none above threshold — skipping notify")
        return

    embed = build_steam_embed(qualifying)

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
            logger.info(
                f"Steam: posted {len(qualifying)} deals to {guild.name}"
            )

        except discord.Forbidden:
            logger.warning(f"Steam: no permission to post in guild {guild.id}")
        except Exception as e:
            logger.error(f"Steam: failed to post to guild {guild.id}: {e}")


# ==================================================
# MAIN UPDATE
# ==================================================

async def update_steam_cache(bot: discord.Client, session, redis=None) -> None:
    """
    Fetch, diff, notify. Called by the background loop.
    """
    logger.info("Steam: fetching deals...")

    try:
        new_games = await fetch_steam_discounts(session, min_discount=0)
    except Exception as e:
        logger.error(f"Steam fetch error: {e}")
        return

    if not new_games:
        logger.warning("Steam: fetch returned empty")
        return

    old_games = await _get_cached(redis)
    new_only  = diff_games(old_games, new_games)

    await _set_cached(new_games, redis)

    if not new_only:
        logger.info("Steam: no new deals detected")
        return

    logger.info(f"Steam: {len(new_only)} new deal(s) — notifying guilds")
    await _notify_guilds(bot, new_only)


async def steam_poster_loop(bot: discord.Client, session, redis=None) -> None:
    """
    Background task. Starts after bot is ready, polls every 2 hours.
    Add to main.py:
        asyncio.create_task(steam_poster_loop(bot, session, cache))
    """
    await bot.wait_until_ready()
    logger.info("Steam poster loop started")

    ERROR_BASE  = 30
    ERROR_MAX   = 300
    error_count = 0

    while True:
        try:
            await update_steam_cache(bot, session, redis)
            error_count = 0
            await asyncio.sleep(STEAM_UPDATE_INTERVAL)

        except asyncio.CancelledError:
            logger.info("Steam poster loop cancelled")
            break
        except Exception as e:
            error_count += 1
            backoff = min(ERROR_BASE * (2 ** (error_count - 1)), ERROR_MAX)
            logger.error(f"Steam loop error: {e} — retrying in {backoff}s")
            await asyncio.sleep(backoff)
