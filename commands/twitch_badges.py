import discord
from discord import app_commands
from services.twitch import fetch_twitch_badges
from utils.pagination import RedisPagination
from config import PLATFORM_COLORS


TWITCH_FALLBACK_ICON = "https://static-cdn.jtvnw.net/emoticons/v2/25/default/dark/3.0"


async def register_twitch_badges(bot, session):

    async def badges_callback(interaction: discord.Interaction):

        await interaction.response.defer(thinking=True)

        try:
            badges = await fetch_twitch_badges(session)
        except Exception as e:
            await interaction.followup.send(
                f"Error fetching Twitch badges: {str(e)}",
                ephemeral=True
            )
            return

        if not badges:
            await interaction.followup.send(
                "No new Twitch badges found.",
                ephemeral=True
            )
            return

        pages = []

        for i in range(0, len(badges), 2):
            chunk = badges[i:i+2]
            description_block = ""

            for b in chunk:
                title = b.get("title", "Unknown Badge")
                description = b.get("description", "No description available.")
                description_block += f"**{title}**\n{description}\n\n"

            embed = discord.Embed(
                title="Global Badges",
                description=description_block.strip(),
                color=PLATFORM_COLORS.get("twitch", 0x9146FF)
            )

            primary_badge = chunk[0]
            thumbnail_url = primary_badge.get("thumbnail")

            if thumbnail_url and thumbnail_url.startswith("http"):
                embed.set_thumbnail(url=thumbnail_url)
            else:
                embed.set_thumbnail(url=TWITCH_FALLBACK_ICON)

            embed.set_footer(
                text=f"Twitch • Page {i//2+1}/{(len(badges)+1)//2}"
            )

            pages.append(embed)

        view = RedisPagination(pages, interaction.user.id)

        await interaction.followup.send(
            embed=pages[0],
            view=view
        )

    command = app_commands.Command(
        name="twitch_badges",
        description="Show latest Twitch global badges",
        callback=badges_callback
    )

    bot.tree.add_command(command)
