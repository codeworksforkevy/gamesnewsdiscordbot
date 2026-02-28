import logging
import discord
from discord import app_commands

from services.free_games_service import (
    update_free_games_cache,
    get_cached_free_games
)
from config import PLATFORM_COLORS

logger = logging.getLogger("free-games-command")


# ==================================================
# REGISTER COMMAND
# ==================================================

async def register(bot, session):

    @bot.tree.command(
        name="freegames",
        description="Show current free games"
    )
    async def freegames(interaction: discord.Interaction):

        await interaction.response.defer(thinking=True)

        try:
            # Cache update (non-blocking safety)
            await update_free_games_cache(session)

            games = await get_cached_free_games()

        except Exception as e:
            logger.exception(
                "Freegames command failed",
                extra={"extra_data": {"error": str(e)}}
            )
            await interaction.followup.send(
                "Failed to fetch free games.",
                ephemeral=True
            )
            return

        if not games:
            await interaction.followup.send(
                "No free games found.",
                ephemeral=True
            )
            return

        # Limit to avoid Discord rate issues
        MAX_GAMES = 15
        games = games[:MAX_GAMES]

        for game in games:

            embed = discord.Embed(
                title=game.get("title", "Unknown Title"),
                url=game.get("url"),
                color=PLATFORM_COLORS.get(
                    game.get("platform"),
                    0xFFFFFF
                )
            )

            if game.get("thumbnail"):
                embed.set_thumbnail(url=game["thumbnail"])

            embed.set_footer(
                text=str(game.get("platform", "Unknown")).upper()
            )

            await interaction.followup.send(embed=embed)

        logger.info(
            "Freegames command executed",
            extra={"extra_data": {"count": len(games)}}
        )
