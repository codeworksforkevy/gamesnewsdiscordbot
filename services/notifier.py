# services/notifier.py

import logging
import discord

logger = logging.getLogger("notifier")


async def notify_new_games(bot, games):

    if not games:
        return

    # TODO: config'den alınabilir
    channel_id = None

    # fallback: ilk guild'in ilk text channel'ı
    channel = None

    for guild in bot.guilds:
        for ch in guild.text_channels:
            channel = ch
            break
        if channel:
            break

    if not channel:
        logger.warning("No channel found for notifications")
        return

    for game in games:
        try:
            embed = discord.Embed(
                title=game.get("title"),
                url=game.get("url"),
                description=f"🎮 Free on {game.get('platform')}",
                color=0x00ff99
            )

            if game.get("thumbnail"):
                embed.set_image(url=game["thumbnail"])

            await channel.send(embed=embed)

        except Exception as e:
            logger.warning(
                "Notify failed",
                extra={"extra_data": {"error": str(e)}}
            )
