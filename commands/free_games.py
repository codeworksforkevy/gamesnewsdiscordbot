import discord
from services.epic import fetch_epic_free
from services.gog import fetch_gog_free
from services.humble import fetch_humble_free
from utils.pagination import RedisPagination
from config import GUILD_ID, PLATFORM_COLORS

async def register_free_games(bot, session):

    @bot.tree.command(name="free_games", description="All free games grouped by platform", guild=discord.Object(id=GUILD_ID))
    async def free_games(interaction: discord.Interaction):

        epic = await fetch_epic_free(session)
        gog = await fetch_gog_free(session)
        humble = await fetch_humble_free(session)

        platform_groups = {"epic": epic, "gog": gog, "humble": humble}
        pages = []

        for platform, games in platform_groups.items():
            if not games:
                continue
            for i in range(0, len(games), 2):
                chunk = games[i:i+2]
                desc = ""
                for g in chunk:
                    desc += f"**{g['title']}**\n{g['url']}\n\n"

                embed = discord.Embed(
                    title=f"{platform.upper()} Free Games",
                    description=desc,
                    color=PLATFORM_COLORS.get(platform)
                )
                embed.set_footer(text=f"{platform.upper()} • Page {i//2+1}/{(len(games)+1)//2}")
                pages.append(embed)

        if not pages:
            await interaction.response.send_message("No free games found.", ephemeral=True)
            return

        view = RedisPagination(pages, interaction.user.id)
        await interaction.response.send_message(embed=pages[0], view=view)
