import discord
from discord import app_commands
from services.epic import fetch_epic_free
from services.gog import fetch_gog_free
from services.humble import fetch_humble_free
from config import PLATFORM_COLORS


async def register_free_games(bot, session):

    async def free_games_callback(interaction: discord.Interaction):

        await interaction.response.defer()

        epic = await fetch_epic_free(session)
        gog = await fetch_gog_free(session)
        humble = await fetch_humble_free(session)

        all_games = epic + gog + humble

        if not all_games:
            await interaction.followup.send(
                "No free games found.",
                ephemeral=True
            )
            return

        embeds = []

        for game in all_games:

            embed = discord.Embed(
                title=game["title"],
                url=game["url"],
                color=PLATFORM_COLORS.get(game["platform"], 0x5865F2)
            )

            embed.add_field(
                name="Platform",
                value=game["platform"].upper(),
                inline=True
            )

            thumb = game.get("thumbnail")
            if thumb and isinstance(thumb, str) and thumb.startswith("http"):
                embed.set_thumbnail(url=thumb)

            embeds.append(embed)

        # Discord allows max 10 embeds per message
        await interaction.followup.send(
            embeds=embeds[:10]
        )

    command = app_commands.Command(
        name="free_games",
        description="Show all current free games",
        callback=free_games_callback
    )

    bot.tree.add_command(command)
