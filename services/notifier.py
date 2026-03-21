import logging
import asyncio
import json
import hashlib
import discord

from core.event_bus import event_bus
from db.guild_settings import get_guild_config

logger = logging.getLogger("notifier")

_memory_last_hash = None


# =================================================
# HASH
# =================================================
def hash_games(games):
    return hashlib.sha256(
        json.dumps(games, sort_keys=True).encode()
    ).hexdigest()


# =================================================
# RETRY
# =================================================
async def retry_async(func, retries=3, delay=2):
    for attempt in range(retries):
        try:
            return await func()
        except Exception as e:
            await asyncio.sleep(delay * (2 ** attempt))

    raise RuntimeError("Max retries exceeded")


# =================================================
# EMBED
# =================================================
def build_embed(game):
    embed = discord.Embed(
        title=game.get("title", "Unknown"),
        url=game.get("url"),
        description=f"🎮 Free on **{game.get('platform', 'Unknown')}**",
        color=0x2ecc71
    )

    if game.get("thumbnail"):
        embed.set_image(url=game["thumbnail"])

    return embed


# =================================================
# EVENT HANDLER
# =================================================
async def handle_free_games(bot, games):

    global _memory_last_hash

    if not games:
        return

    current_hash = hash_games(games)

    if current_hash == _memory_last_hash:
        logger.info("Duplicate skipped")
        return

    _memory_last_hash = current_hash

    # group embeds
    embeds = [build_embed(g) for g in games]

    # send per guild config (DB DRIVEN)
    for guild in bot.guilds:

        config = await get_guild_config(guild.id)

        if not config:
            continue

        channel_id = config.get("announce_channel_id")

        if not channel_id:
            continue

        channel = guild.get_channel(channel_id)

        if not channel:
            continue

        try:
            # chunk send
            for i in range(0, len(embeds), 10):
                await retry_async(lambda: channel.send(embeds=embeds[i:i+10]))

            await retry_async(lambda: channel.send(f"🔥 {len(games)} new free games!"))

        except Exception as e:
            logger.error(f"Send failed: {e}")


# =================================================
# EVENT SUBSCRIBE
# =================================================
def register_notifier(bot):

    async def _wrapper(games):
        await handle_free_games(bot, games)

    event_bus.subscribe("free_games_fetched", _wrapper)
