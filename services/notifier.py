import logging
import asyncio
import json
import hashlib
import discord

from services.channel_registry import get_channels

logger = logging.getLogger("notifier")

CACHE_KEY = "notified_games_hash"
_memory_last_hash = None


# ==================================================
# HASHING (DEDUP)
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
# MAIN NOTIFIER (MULTI-GUILD)
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

    if redis:
        try:
            last_hash = await redis.get(CACHE_KEY)

            if isinstance(last_hash, bytes):
                last_hash = last_hash.decode()

            if last_hash == current_hash:
                logger.info("Duplicate skipped (Redis)")
                return

        except Exception as e:
            logger.warning(f"Redis hash check failed: {e}")

    if _memory_last_hash == current_hash:
        logger.info("Duplicate skipped (Memory)")
        return

    # -------------------------
    # CHANNELS (MULTI)
    # -------------------------
    channels = get_channels(bot)

    if not channels:
        logger.warning("No channels configured")
        return

    # -------------------------
    # GROUP UX
    # -------------------------
    grouped = group_by_platform(games)

    # -------------------------
    # SEND TO ALL CHANNELS
    # -------------------------
    for ch in channels:

        guild_id = ch.get("guild_id")
        channel_id = ch.get("channel_id")

        try:
            channel = bot.get_channel(channel_id)

            if not channel:
                channel = await bot.fetch_channel(channel_id)

        except Exception as e:
            logger.warning(
                "Channel access failed",
                extra={"extra_data": {"guild_id": guild_id, "error": str(e)}}
            )
            continue

        # send grouped content
        for platform, items in grouped.items():

            embeds = []

            for game in items:
                try:
                    embeds.append(build_embed(game))
                except Exception as e:
                    logger.warning(f"Embed build failed: {e}")

            # chunk (max 10)
            for i in range(0, len(embeds), 10):
                chunk = embeds[i:i + 10]

                try:
                    await retry_async(lambda: channel.send(embeds=chunk))
                except Exception as e:
                    logger.error(
                        "Send failed",
                        extra={
                            "extra_data": {
                                "guild_id": guild_id,
                                "error": str(e)
                            }
                        }
                    )

        # summary per guild
        try:
            summary = f"🔥 {len(games)} new free games!"

            await retry_async(lambda: channel.send(summary))

        except Exception as e:
            logger.warning(f"Summary failed: {e}")

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

    # -------------------------
    # LOG
    # -------------------------
    logger.info(
        "Games notified",
        extra={"extra_data": {"count": len(games), "channels": len(channels)}}
    )
