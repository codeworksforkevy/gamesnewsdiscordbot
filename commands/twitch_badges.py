import discord
from discord import app_commands
from services.twitch import (
    fetch_twitch_badges,
    fetch_official_global_badges
)
from utils.pagination import RedisPagination
from config import PLATFORM_COLORS


TWITCH_FALLBACK_ICON = "https://static-cdn.jtvnw.net/emoticons/v2/25/default/dark/3.0"


def match_badge_thumbnail(title, official_map):
    title = title.lower()

    for key, url in official_map.items():
        if key in title:
            return url

    return None


async def register_twitch_badges(bot, session):

    async def badges_callback(interaction: discord.Interaction):

        await interaction.response.defer(thinking=True)

        try:
            badges = await fetch_twitch_badges(session)
            official_badges = await fetch_official_global_badges(session)
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
            desc_block = ""

            for b in chunk:
                desc_block += f"**{b['title']}**\n{b['description']}\n\n"

            embed = discord.Embed(
                title="Global Badges",
                description=desc_block.strip(),
                color=PLATFORM_COLORS.get("twitch", 0x9146FF)
            )

            primary = chunk[0]
            thumbnail = match_badge_thumbnail(
                primary["title"],
                official_badges
            )

            if not thumbnail:
                thumbnail = TWITCH_FALLBACK_ICON

            embed.set_thumbnail(url=thumbnail)

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


    bot.tree.add_command(command)
