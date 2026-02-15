import discord
from services.epic import fetch_epic_free
from services.gog import fetch_gog_free
from services.humble import fetch_humble_free
from utils.pagination import RedisPagination
from config import GUILD_ID, PLATFORM_COLORS

def build_embed(title, games, color):
    desc = ""
    for g in games[:2]:
        desc += f"**{g['title']}**\n{g['url']}\n\n"
    embed = discord.Embed(title=title, description=desc, color=color)
    if games and games[0].get("thumbnail"):
        embed.set_thumbnail(url=games[0]["thumbnail"])
    return embed

async def register_free_games(bot, session):

    @bot.tree.command(name="free_games", description="Grouped free games", guild=discord.Object(id=GUILD_ID))
    async def free_games(interaction: discord.Interaction):
        epic = await fetch_epic_free(session)
        gog = await fetch_gog_free(session)
        humble = await fetch_humble_free(session)

        pages = []

        if epic:
            pages.append(build_embed("EPIC Free Games", epic, PLATFORM_COLORS["epic"]))
        if gog:
            pages.append(build_embed("GOG Free Games", gog, PLATFORM_COLORS["gog"]))
        if humble:
            pages.append(build_embed("HUMBLE Free Games", humble, PLATFORM_COLORS["humble"]))

        if not pages:
            await interaction.response.send_message("No free games found.", ephemeral=True)
            return

        view = RedisPagination(pages)
        await interaction.response.send_message(embed=pages[0], view=view)

    @bot.tree.command(name="freegames_now", description="Force show free games (Admin only)", guild=discord.Object(id=GUILD_ID))
    @discord.app_commands.checks.has_permissions(administrator=True)
    async def freegames_now(interaction: discord.Interaction):
        epic = await fetch_epic_free(session)
        if not epic:
            await interaction.response.send_message("No games found.", ephemeral=True)
            return
        embed = build_embed("FORCED Free Games Snapshot", epic, PLATFORM_COLORS["epic"])
        await interaction.response.send_message(embed=embed)
