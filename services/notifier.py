import logging
import asyncio
import json
import hashlib
import discord

logger = logging.getLogger("notifier")

CACHE_KEY = "notified_games_hash"

_memory_last_hash = None


# ==================================================
# HASHING (DEDUP SYSTEM)
# ==================================================

def hash_games(games):
    try:
        return hashlib.sha256(
            json.dumps(games, sort_keys=True).encode()
        ).hexdigest()
    except Exception:
        return None


# ==================================================
# RETRY HELPER
# ==================================================

async def retry_async(func, retries=3, delay=2):
    last_error = None

    for attempt in range(retries):
        try:
            return await func()
        except Exception as e:
            last_error = e
            await asyncio.sleep(delay * (2 ** attempt))

    raise last_error


# ==================================================
# EMBED BUILDER (UX)
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

    if game.get("expires"):
        embed.add_field(
            name="⏳ Expires",
            value=str(game["expires"]),
            inline=True
        )

    if game.get("price"):
        embed.add_field(
            name="💰 Price",
            value=str(game["price"]),
            inline=True
        )

    embed.set_footer(text="Free Games Bot")

    return embed


# ==================================================
# GROUP BY PLATFORM (UX)
# ==================================================

def group_by_platform(games):
    grouped = {}

    for game in games:
        platform = game.get("platform", "Unknown")

        if platform not in grouped:
            grouped[platform] = []

        grouped[platform].append(game)

    return grouped


# ==================================================
# MAIN NOTIFIER
# ==================================================

async def notify_discord(bot, games, redis=None):

    if not games:
        return

    global _memory_last_hash

    # -------------------------
    # DEDUP CHECK
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
                logger.info("Duplicate notification skipped (Redis)")
                return

        except Exception as e:
            logger.warning(
                "Redis hash check failed",
                extra={"extra_data": {"error": str(e)}}
            )

    # Memory fallback
    if _memory_last_hash == current_hash:
        logger.info("Duplicate notification skipped (Memory)")
        return

    # -------------------------
    # CHANNEL
    # -------------------------
    try:
        channel_id = int(bot.app_state.default_channel_id)
    except Exception as e:
        logger.error(
            "Invalid channel ID",
            extra={"extra_data": {"error": str(e)}}
        )
        return

    channel = bot.get_channel(channel_id)

    if not channel:
        try:
            channel = await bot.fetch_channel(channel_id)
        except Exception as e:
            logger.error(
                "Channel fetch failed",
                extra={"extra_data": {"error": str(e)}}
            )
            return

    # -------------------------
    # GROUP UX
    # -------------------------
    grouped = group_by_platform(games)

    # -------------------------
    # SEND MESSAGE PER PLATFORM
    # -------------------------
    for platform, items in grouped.items():

        embeds = []

        for game in items:
            try:
                embeds.append(build_embed(game))
            except Exception as e:
                logger.warning(
                    "Embed build failed",
                    extra={"extra_data": {"error": str(e)}}
                )

        chunks = [embeds[i:i + 10] for i in range(0, len(embeds), 10)]

        for chunk in chunks:
            try:
                await retry_async(lambda: channel.send(embeds=chunk))
            except Exception as e:
                logger.exception(
                    "Send failed",
                    extra={"extra_data": {"error": str(e)}}
                )

    # -------------------------
    # SUMMARY MESSAGE (UX BOOST)
    # -------------------------
    try:
        summary = f"🔥 **{len(games)} New Free Games Available!**"

        await retry_async(lambda: channel.send(summary))
    except Exception as e:
        logger.warning(
            "Summary send failed",
            extra={"extra_data": {"error": str(e)}}
        )

    # -------------------------
    # SAVE HASH
    # -------------------------
    try:
        if redis:
            await redis.set(CACHE_KEY, current_hash)
        else:
            _memory_last_hash = current_hash

    except Exception as e:
        logger.warning(
            "Hash save failed",
            extra={"extra_data": {"error": str(e)}}
        )

    # -------------------------
    # LOG
    # -------------------------
    logger.info(
        "Games notified",
        extra={"extra_data": {"count": len(games)}}
    )
