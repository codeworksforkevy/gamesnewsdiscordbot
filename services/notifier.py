import logging
import asyncio
import json
import hashlib
from typing import List, Dict, Any, Optional

import discord

from core.event_bus import event_bus
from db.guild_settings import get_guild_config

logger = logging.getLogger("notifier")

# =================================================
# UTILS
# =================================================

def hash_games(games: List[Dict[str, Any]]) -> str:
    """
    Deterministic hash for deduplication
    """
    payload = json.dumps(games, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


async def retry_async(func, retries: int = 3, delay: int = 2):
    """
    Exponential backoff retry wrapper
    """
    last_error = None

    for attempt in range(retries):
        try:
            return await func()
        except Exception as e:
            last_error = e
            await asyncio.sleep(delay * (2 ** attempt))

    raise RuntimeError(f"Max retries exceeded: {last_error}")


def build_embed(game: Dict[str, Any]) -> discord.Embed:
    """
    Build Discord embed from game object
    """
    embed = discord.Embed(
        title=game.get("title", "Unknown"),
        url=game.get("url"),
        description=f"🎮 Free on **{game.get('platform', 'Unknown')}**",
        color=0x2ecc71
    )

    thumbnail = game.get("thumbnail")
    if thumbnail:
        embed.set_image(url=thumbnail)

    return embed


# =================================================
# NOTIFIER STATE
# =================================================

class NotifierState:
    """
    Keeps runtime state (thread-safe per process)
    """

    def __init__(self):
        self.last_hash: Optional[str] = None


state = NotifierState()


# =================================================
# CORE HANDLER
# =================================================

async def handle_free_games(bot: discord.Client, games: List[Dict[str, Any]]):
    """
    Main notification handler
    """

    if not games:
        return

    current_hash = hash_games(games)

    # Deduplication
    if state.last_hash == current_hash:
        logger.info("Duplicate skipped")
        return

    state.last_hash = current_hash

    embeds = [build_embed(game) for game in games]

    # Iterate guilds
    for guild in bot.guilds:

        try:
            config = await get_guild_config(guild.id)

            if not config:
                continue

            channel_id = config.get("announce_channel_id")

            if not channel_id:
                continue

            # FIX: fetch_channel fallback
            channel = guild.get_channel(channel_id) or await bot.fetch_channel(channel_id)

            if not channel:
                continue

            # Send embeds in chunks (Discord limit safety)
            for i in range(0, len(embeds), 10):
                chunk = embeds[i:i + 10]

                await retry_async(
                    lambda: channel.send(embeds=chunk)
                )

            await retry_async(
                lambda: channel.send(f"🔥 {len(games)} new free games!")
            )

        except Exception as e:
            logger.error(f"Guild send failed (guild_id={guild.id}): {e}")


# =================================================
# EVENT REGISTRATION
# =================================================

def register_notifier(bot: discord.Client):
    """
    Registers notifier to event bus
    """

    async def _handler(games):
        await handle_free_games(bot, games)

    event_bus.subscribe("free_games_fetched", _handler)
