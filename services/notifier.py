import logging
import asyncio
import discord

logger = logging.getLogger("notifier")


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
# EMBED BUILDER (UX IMPROVED)
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

    # Optional fields
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
# MAIN NOTIFIER (SAFE + UX + RETRY)
# ==================================================

async def notify_discord(bot, games):

    if not games:
        return

    # -------------------------
    # CHANNEL FETCH
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
        logger.warning("Notify channel not found in cache, trying fetch...")

        try:
            channel = await bot.fetch_channel(channel_id)
        except Exception as e:
            logger.error(
                "Channel fetch failed",
                extra={"extra_data": {"error": str(e)}}
            )
            return

    # -------------------------
    # SEND IN BATCH (UX IMPROVEMENT)
    # -------------------------
    embeds = []

    for game in games:
        try:
            embeds.append(build_embed(game))
        except Exception as e:
            logger.warning(
                "Embed build failed",
                extra={"extra_data": {"error": str(e), "game": game}}
            )

    # Discord limits: max 10 embeds per message
    chunks = [embeds[i:i + 10] for i in range(0, len(embeds), 10)]

    for chunk in chunks:
        try:
            await retry_async(lambda: channel.send(embeds=chunk))
        except Exception as e:
            logger.exception(
                "Discord send failed",
                extra={"extra_data": {"error": str(e)}}
            )

    # -------------------------
    # LOGGING
    # -------------------------
    logger.info(
        "Games notified",
        extra={"extra_data": {"count": len(games)}}
    )
