import logging
import asyncio
import json
import hashlib
import discord

from core.event_bus import event_bus
from core.state_manager import state_manager

logger = logging.getLogger("notifier")

CACHE_KEY = "notified_games_hash"

_memory_last_hash = None


# ==================================================
# HASH (DEDUP)
# ==================================================
def hash_games(games):
    try:
        return hashlib.sha256(
            json.dumps(games, sort_keys=True).encode()
        ).hexdigest()
    except Exception:
        return None


# ==================================================
# RETRY (ROBUST)
# ==================================================
async def retry_async(func, retries=3, base_delay=1):
    last_error = None

    for attempt in range(retries):
        try:
            return await func()
        except Exception as e:
            last_error = e
            await asyncio.sleep(base_delay * (2 ** attempt))

    raise last_error


# ==================================================
# EMBED BUILDER (UX ENHANCED)
# ==================================================
def build_embed(game):
    embed = discord.Embed(
        title=game.get("title", "Unknown Game"),
        url=game.get("url"),
        description=f"🎮 Free on **{game.get('platform', 'Unknown')}**",
        color=0x2ecc71
    )

    if game.get("thumbnail"):
        embed.set_image(url=game["thumbnail"])

    if game.get("end_date"):
        embed.add_field(
            name="⏳ Expires",
            value=str(game["end_date"]),
            inline=True
        )

    embed.set_footer(text="Curie Free Games Bot")

    return embed


# ==================================================
# GROUP BY PLATFORM (UX)
# ==================================================
def group_by_platform(games):
    grouped = {}

    for game in games:
        platform = game.get("platform", "Unknown")
        grouped.setdefault(platform, []).append(game)

    return grouped


# ==================================================
# SAFE CHANNEL RESOLVE (MULTI-GUILD)
# ==================================================
async def resolve_channel(bot, guild_id: int):
    try:
        state = await state_manager.get_guild_state(guild_id)

        if not state:
            return None

        channel_id = state.get("channel_id")

        if not channel_id:
            return None

        channel = bot.get_channel(channel_id)

        if channel:
            return channel

        return await bot.fetch_channel(channel_id)

    except Exception as e:
        logger.warning(
            "Channel resolve failed",
            extra={"guild_id": guild_id, "error": str(e)}
        )
        return None


# ==================================================
# CORE NOTIFIER (EVENT HANDLER)
# ==================================================
async def handle_new_games(data):
    """
    Event-driven handler:
    triggered by event_bus.publish("new_games", games)
    """

    bot = data.get("bot")
    games = data.get("games")
    redis = data.get("redis")

    if not bot or not games:
        return

    global _memory_last_hash

    # -------------------------
    # DEDUP
    # -------------------------
    current_hash = hash_games(games)

    if not current_hash:
        logger.warning("Hash generation failed")
        return

    # Redis check
    if redis:
        try:
            last_hash = await redis.get(CACHE_KEY)

            if isinstance(last_hash, bytes):
                last_hash = last_hash.decode()

            if last_hash == current_hash:
                logger.info("Duplicate skipped (Redis)")
                return

        except Exception as e:
            logger.warning(f"Redis check failed: {e}")

    # Memory check
    if _memory_last_hash == current_hash:
        logger.info("Duplicate skipped (Memory)")
        return

    # -------------------------
    # GROUP UX
    # -------------------------
    grouped = group_by_platform(games)

    # -------------------------
    # GET ALL GUILDS
    # -------------------------
    guilds = bot.guilds

    tasks = []

    for guild in guilds:
        tasks.append(process_guild(bot, guild, grouped))

    await asyncio.gather(*tasks, return_exceptions=True)

    # -------------------------
    # SAVE HASH
    # -------------------------
    try:
        if redis:
            await redis.set(CACHE_KEY, current_hash)
        else:
            _memory_last_hash = current_hash
    except Exception as e:
        logger.warning(f"Hash save failed: {e}")

    logger.info(
        "Games notified",
        extra={"count": len(games), "guilds": len(guilds)}
    )


# ==================================================
# PER GUILD PROCESSING
# ==================================================
async def process_guild(bot, guild, grouped):

    try:
        channel = await resolve_channel(bot, guild.id)

        if not channel:
            logger.warning(f"No channel for guild {guild.id}")
            return

        # -------------------------
        # SEND PER PLATFORM
        # -------------------------
        for platform, games in grouped.items():

            embeds = []

            for game in games:
                try:
                    embeds.append(build_embed(game))
                except Exception as e:
                    logger.warning(f"Embed error: {e}")

            # chunk
            for i in range(0, len(embeds), 10):
                chunk = embeds[i:i + 10]

                await retry_async(lambda: channel.send(embeds=chunk))

        # -------------------------
        # SUMMARY
        # -------------------------
        summary = f"🔥 {sum(len(v) for v in grouped.values())} new free games!"

        await retry_async(lambda: channel.send(summary))

    except Exception as e:
        logger.error(
            "Guild processing failed",
            extra={"guild_id": guild.id, "error": str(e)}
        )


# ==================================================
# REGISTER EVENT HANDLER
# ==================================================
async def register_notifier():
    await event_bus.subscribe("new_games", handle_new_games)
