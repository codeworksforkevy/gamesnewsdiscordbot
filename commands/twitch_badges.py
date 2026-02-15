import discord
from discord import app_commands
from services.twitch import fetch_twitch_badges
from utils.pagination import RedisPagination
from config import PLATFORM_COLORS


async def register_twitch_badges(bot, session):

    async def badges_callback(interaction: discord.Interaction):

        badges = await fetch_twitch_badges(session)

        if not badges:
            await interaction.response.send_message(
                "No new Twitch badges found.",
                ephemeral=True
            )
            return

        pages = []

        for i in range(0, len(badges), 2):
            chunk = badges[i:i+2]
            desc = ""

            for b in chunk:
                desc += f"**{b['title']}**\n{b['description']}\n\n"

            embed = discord.Embed(
                title="Twitch Global Badges",
                description=desc,
                color=PLATFORM_COLORS.get("twitch")
            )

            if chunk[0].get("thumbnail"):
                embed.set_thumbnail(url=chunk[0]["thumbnail"])

            embed.set_footer(text=f"Twitch • Page {i//2+1}")
            pages.append(embed)

        view = RedisPagination(pages, interaction.user.id)
        await interaction.response.send_message(embed=pages[0], view=view)

    command = app_commands.Command(
        name="twitch_badges",
        description="Show latest Twitch global badges",
        callback=badges_callback
    )

    bot.tree.add_command(command)
