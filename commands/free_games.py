import discord
from discord import app_commands
from services.epic import fetch_epic_free
from services.gog import fetch_gog_free
from services.humble import fetch_humble_free
from utils.pagination import RedisPagination
from config import PLATFORM_COLORS


async def register_free_games(bot, session):

    async def free_games_callback(interaction: discord.Interaction):

        epic = await fetch_epic_free(session)
        gog = await fetch_gog_free(session)
        humble = await fetch_humble_free(session)

        platform_groups = {
            "epic": epic,
            "gog": gog,
            "humble": humble
        }

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
                    color=PLATFORM_COLORS.get(platform, 0x5865F2)
                )

                if chunk[0].get("thumbnail"):
                    embed.set_thumbnail(url=chunk[0]["thumbnail"])

                embed.set_footer(text=f"{platform.upper()} • Page {i//2+1}")

                pages.append(embed)

        if not pages:
            await interaction.response.send_message(
                "No free games found.",
                ephemeral=True
            )
            return

        view = RedisPagination(pages, interaction.user.id)
        await interaction.response.send_message(embed=pages[0], view=view)

    command = app_commands.Command(
        name="free_games",
        description="Show all current free games grouped by platform",
        callback=free_games_callback
    )

    bot.tree.add_command(command)

