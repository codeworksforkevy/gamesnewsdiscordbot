import discord
from discord import app_commands
from services.steam import fetch_steam_discounts
from utils.pagination import RedisPagination
from config import PLATFORM_COLORS


async def register(bot, session):

    async def discounts_callback(interaction: discord.Interaction):

        steam_games = await fetch_steam_discounts(session)

        if not steam_games:
            await interaction.response.send_message(
                "No major discounts found.",
                ephemeral=True
            )
            return

        pages = []

        for i in range(0, len(steam_games), 2):
            chunk = steam_games[i:i+2]
            desc = ""

            for g in chunk:
                desc += (
                    f"**{g['title']}**\n"
                    f"{g.get('discount','On Sale')} OFF\n"
                    f"{g['url']}\n\n"
                )

            embed = discord.Embed(
                title="Steam Major Discounts",
                description=desc.strip(),
                color=PLATFORM_COLORS.get("steam")
            )

            if chunk[0].get("thumbnail"):
                embed.set_thumbnail(url=chunk[0]["thumbnail"])

            embed.set_footer(text=f"Steam • Page {i//2+1}")
            pages.append(embed)

        view = RedisPagination(pages, interaction.user.id)

        await interaction.response.send_message(
            embed=pages[0],
            view=view
        )

    bot.tree.add_command(
        app_commands.Command(
            name="game_discounts",
            description="Show current major game discounts",
            callback=discounts_callback
        )
    )
