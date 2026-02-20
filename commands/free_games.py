import json
import discord
from config import PLATFORM_COLORS

CACHE_FILE = "data/free_games_cache.json"


async def register(bot, session=None):

    @bot.tree.command(
        name="freegames",
        description="Show cached free games"
    )
    async def freegames(interaction: discord.Interaction):

        await interaction.response.defer()

        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            await interaction.followup.send(
                "Cache not available.",
                ephemeral=True
            )
            return

        games = data.get("games", [])

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
                color=PLATFORM_COLORS.get(
                    game.get("platform"),
                    0xFFFFFF
                )
            )

            if game.get("thumbnail"):
                embed.set_thumbnail(url=game["thumbnail"])

            embed.set_footer(
                text=game.get("platform", "").upper()
            )

            await interaction.followup.send(embed=embed)
