import discord
from discord import app_commands
from services.epic import fetch_epic_free
from services.gog import fetch_gog_free
from services.humble import fetch_humble_free
from utils.pagination import RedisPagination
from config import PLATFORM_COLORS


async def register_free_games(bot, session):

    async def free_games_callback(interaction: discord.Interaction):

        await interaction.response.defer(thinking=True)

        try:
            epic = await fetch_epic_free(session)
            print("Epic games fetched:", len(epic))
        except Exception as e:
            epic = []
            print("Epic fetch error:", e)

        try:
            gog = await fetch_gog_free(session)
            print("GOG games fetched:", len(gog))
        except Exception as e:
            gog = []
            print("GOG fetch error:", e)

        try:
            humble = await fetch_humble_free(session)
            print("Humble games fetched:", len(humble))
        except Exception as e:
            humble = []
            print("Humble fetch error:", e)

        platform_groups = {
            "epic": epic or [],
            "gog": gog or [],
            "humble": humble or []
        }

        print("Platform distribution:", {k: len(v) for k, v in platform_groups.items()})

        pages = []

        for platform, games in platform_groups.items():

            if not games:
                continue

            total_pages = (len(games) + 1) // 2

            for i in range(0, len(games), 2):

                chunk = games[i:i+2]
                desc = ""

                for g in chunk:
                    title = g.get("title", "Unknown Game")
                    url = g.get("url", "No URL available")
                    desc += f"**{title}\n{url}\n\n"

                embed = discord.Embed(
                    title=f"{platform.upper()} Free Games",
                    description=desc.strip(),
                    color=PLATFORM_COLORS.get(platform, 0x5865F2)
                )

                thumbnail = chunk[0].get("thumbnail")
                if thumbnail and isinstance(thumbnail, str) and thumbnail.startswith("http"):
                    embed.set_thumbnail(url=thumbnail)

                embed.set_footer(
                    text=f"{platform.upper()} • Page {i//2 + 1}/{total_pages}"
                )

                pages.append(embed)

        if not pages:
            await interaction.followup.send(
                "No free games found.",
                ephemeral=True
            )
            return

        view = RedisPagination(pages, interaction.user.id)

        await interaction.followup.send(
            embed=pages[0],
            view=view
        )

    command = app_commands.Command(
        name="free_games",
        description="Show all current free games grouped by platform",
        callback=free_games_callback
    )

    bot.tree.add_command(command)

