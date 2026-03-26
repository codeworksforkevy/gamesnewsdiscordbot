# services/notifier.py
#
# UX upgrade: each free game embed now has a "Claim now" button
# linking directly to the store page.

import logging
import asyncio
import json
import hashlib
from typing import List, Dict, Any, Optional

import discord

from core.event_bus import event_bus
from db.guild_settings import get_guild_config

logger = logging.getLogger("notifier")


# ==================================================
# UTILS
# ==================================================

def hash_games(games: List[Dict[str, Any]]) -> str:
    payload = json.dumps(games, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()


async def retry_async(func, retries: int = 3, delay: int = 2):
    last_error = None
    for attempt in range(retries):
        try:
            return await func()
        except Exception as e:
            last_error = e
            wait = delay * (2 ** attempt)
            logger.warning(f"Retry {attempt + 1}/{retries} — waiting {wait}s: {e}")
            await asyncio.sleep(wait)
    raise RuntimeError(f"Max retries exceeded: {last_error}")


# ==================================================
# CLAIM BUTTON VIEW
# UX: link button attached to each game embed so users
#     can click straight through to the store page.
# timeout=None makes it persistent across bot restarts.
# ==================================================

class ClaimView(discord.ui.View):
    def __init__(self, url: str, platform: str = ""):
        super().__init__(timeout=None)
        label = f"🎮 Claim on {platform}" if platform else "🎮 Claim now"
        self.add_item(
            discord.ui.Button(
                label=label,
                url=url,
                style=discord.ButtonStyle.link,
            )
        )


# ==================================================
# EMBED BUILDER
# ==================================================

def build_embed(game: Dict[str, Any]) -> discord.Embed:
    title     = game.get("title") or game.get("name") or "Unknown Game"
    platform  = game.get("platform") or "Unknown Platform"
    url       = game.get("url") or ""
    thumbnail = game.get("thumbnail") or game.get("image") or ""

    embed = discord.Embed(
        title=title,
        url=url or None,
        description=f"🎮 Free on **{platform.capitalize()}**",
        color=0x2ECC71,
    )

    if thumbnail:
        embed.set_image(url=thumbnail)

    return embed


# ==================================================
# NOTIFIER STATE
# ==================================================

class NotifierState:
    def __init__(self):
        self.last_hash: Optional[str] = None


state = NotifierState()


# ==================================================
# CORE HANDLER
# ==================================================

async def notify_discord(
    bot: discord.Client,
    games: List[Dict[str, Any]],
    redis=None,
) -> None:
    await handle_free_games(bot, games)


async def handle_free_games(
    bot: discord.Client,
    games: List[Dict[str, Any]],
) -> None:
    """
    Send free game embeds + Claim buttons to all guilds' announce channels.
    """
    if not games:
        logger.info("handle_free_games: empty list — skipping")
        return

    current_hash = hash_games(games)
    if state.last_hash == current_hash:
        logger.info("Duplicate game list — skipping")
        return
    state.last_hash = current_hash

    count = len(games)
    label  = "game" if count == 1 else "games"
    header = f"🔥 **{count} new free {label} available!**"

    logger.info(f"Notifying {len(bot.guilds)} guild(s) about {count} free {label}")

    for guild in bot.guilds:
        try:
            config = await get_guild_config(guild.id)
            if not config:
                logger.debug(f"No config for guild {guild.id} — skipping")
                continue

            channel_id = config.get("announce_channel_id")
            if not channel_id:
                logger.debug(f"No announce channel for guild {guild.id} — skipping")
                continue

            channel = guild.get_channel(channel_id) or await bot.fetch_channel(channel_id)
            if not channel:
                logger.warning(f"Channel {channel_id} not found in guild {guild.id}")
                continue

            # Header first — acts as the group title
            await retry_async(lambda: channel.send(header))

            # One embed + claim button per game
            # UX: individual embeds so each has its own clickable button
            for game in games:
                embed    = build_embed(game)
                url      = game.get("url", "")
                platform = (game.get("platform") or "").capitalize()
                view     = ClaimView(url, platform) if url else None

                # FIX: capture loop variables with default args
                await retry_async(
                    lambda e=embed, v=view: channel.send(embed=e, view=v)
                )

            logger.info(f"Notified {guild.name} ({guild.id}) — {count} {label}")

        except discord.Forbidden:
            logger.error(
                f"No permission to post in channel {channel_id} (guild {guild.id})"
            )
        except discord.HTTPException as e:
            logger.error(f"HTTP error for guild {guild.id}: {e.status} {e.text}")
        except Exception as e:
            logger.exception(f"Unexpected error for guild {guild.id}: {e}")


# ==================================================
# EVENT BUS REGISTRATION
# ==================================================

def register_notifier(bot: discord.Client) -> None:
    async def _handler(games: List[Dict[str, Any]]) -> None:
        await handle_free_games(bot, games)

    event_bus.subscribe("free_games_fetched", _handler)
    logger.info("Notifier registered on event bus")
