# services/notifier.py

import logging

logger = logging.getLogger("notifier")


async def notify_discord(bot, games):
    """
    Sends new games to Discord channels
    """

    if not games:
        return

    # TODO: kanal ID'leri config/DB'den alınmalı
    channel_id = int(bot.app_state.default_channel_id)

    channel = bot.get_channel(channel_id)

    if not channel:
        logger.warning("Notify channel not found")
        return

    for game in games:

        embed = {
            "title": game["title"],
            "url": game.get("url"),
            "description": f"Free on {game['platform']}",
        }

        if game.get("thumbnail"):
            embed["image"] = {"url": game["thumbnail"]}

        await channel.send(embed=discord.Embed(**embed))

    logger.info(
        "Games notified",
        extra={"extra_data": {"count": len(games)}}
    )
