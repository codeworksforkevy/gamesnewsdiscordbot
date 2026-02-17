import discord, json
from pathlib import Path
from config import PLATFORM_COLORS

CACHE_FILE = Path("data/free_games_cache.json")

async def register_free_games(tree):

    @tree.command(name="free_games", description="Show cached free games")
    async def free_games(interaction: discord.Interaction):

        if not CACHE_FILE.exists():
            await interaction.response.send_message("Cache not ready.", ephemeral=True)
            return

        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            games = json.load(f)

        if not games:
            await interaction.response.send_message("No free games found.", ephemeral=True)
            return

        embeds = []
        for g in games[:10]:
            embed = discord.Embed(title=g["title"], url=g["url"], color=PLATFORM_COLORS.get(g["platform"],0x5865F2))
            if g.get("thumbnail"):
                embed.set_thumbnail(url=g["thumbnail"])
            embeds.append(embed)

        await interaction.response.send_message(embeds=embeds)
