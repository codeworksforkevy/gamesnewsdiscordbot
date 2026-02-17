import json
import discord
from discord import app_commands
from config import PLATFORM_COLORS

CACHE_FILE = "data/free_games_cache.json"


async def register_free_games(tree):

    @tree.command(name="freegames", description="Show cached free games")
    async def freegames(interaction: discord.Interaction):

        await interaction.response.defer()

        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        except:
            await interaction.followup.send("Cache not available.", ephemeral=True)
            return

        games = data.get("games", [])

        if not games:
            await interaction.followup.send("No free games found.", ephemeral=True)
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
