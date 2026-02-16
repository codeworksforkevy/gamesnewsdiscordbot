import discord
from discord import app_commands
from services.twitch import fetch_twitch_badges
from utils.pagination import RedisPagination
from config import PLATFORM_COLORS


async def register_twitch_badges(bot, session):

    async def badges_callback(interaction: discord.Interaction):

        try:
            badges = await fetch_twitch_badges(session)
        except Exception as e:
            await interaction.response.send_message(
                f"Error fetching Twitch badges: {str(e)}",
                ephemeral=True
            )
            return

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
                title = b.get("title", "Unknown Badge")
                description = b.get("description", "No description available.")
                desc += f"**{title}**\n{description}\n\n"

            embed = discord.Embed(
                title="Global Badges",
                description=desc.strip(),
                color=PLATFORM_COLORS.get("twitch", 0x9146FF)
            )

            # Thumbnail güvenli kontrol
            thumbnail = chunk[0].get("thumbnail")
            if thumbnail and thumbnail.startswith("http"):
                embed.set_thumbnail(url=thumbnail)

            embed.set_footer(
                text=f"Twitch • Page {i//2+1}/{(len(badges)+1)//2}"
            )

            pages.append(embed)

        view = RedisPagination(pages, interaction.user.id)

        await interaction.response.send_message(
            embed=pages[0],
            view=view
        )

    command = app_commands.Command(
        name="twitch_badges",
        description="Show latest Twitch global badges",
        callback=badges_callback
    )

    bot.tree.add_command(command)
