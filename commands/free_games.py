import discord
from discord import app_commands
from services.free_games_service import (
    update_free_games_cache,
    get_cached_free_games
)
from config import PLATFORM_COLORS


async def register(bot, session):

    @bot.tree.command(
        name="freegames",
        description="Show current free games"
    )
    async def freegames(interaction: discord.Interaction):

        await interaction.response.defer(thinking=True)

        # Önce cache'i güncelle (isteğe bağlı)
        await update_free_games_cache(session)

        games = await get_cached_free_games()

        if not games:
            await interaction.followup.send(
                "No free games found.",
                ephemeral=True
            )
            return

        for game in games:

            embed = discord.Embed(
                title=game["title"],
                url=game["url"],
                color=PLATFORM_COLORS.get(game["platform"], 0xFFFFFF)
            )

            if game.get("thumbnail"):
                embed.set_thumbnail(url=game["thumbnail"])

            embed.set_footer(text=game["platform"].upper())

            await interaction.followup.send(embed=embed)
