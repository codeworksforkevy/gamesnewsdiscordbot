import discord
from discord import app_commands
import asyncio
from services.epic import fetch_epic_free
from services.gog import fetch_gog_free
from services.humble import fetch_humble_free
from config import PLATFORM_COLORS


async def register_free_games(bot, session):

    async def safe_fetch(coro):
        try:
            return await asyncio.wait_for(coro, timeout=8)
        except Exception as e:
            print("Fetch error:", e)
            return []

    async def free_games_callback(interaction: discord.Interaction):

        await interaction.response.defer()

        epic_task = safe_fetch(fetch_epic_free(session))
        gog_task = safe_fetch(fetch_gog_free(session))
        humble_task = safe_fetch(fetch_humble_free(session))

        epic, gog, humble = await asyncio.gather(
            epic_task, gog_task, humble_task
        )

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

        await interaction.followup.send(
            embeds=embeds[:10]
        )

    command = app_commands.Command(
        name="free_games",
        description="Show all current free games",
        callback=free_games_callback
    )

    bot.tree.add_command(command)
