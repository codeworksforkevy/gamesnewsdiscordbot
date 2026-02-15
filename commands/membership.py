import discord
from discord import app_commands
from services.luna import fetch_luna_membership
from utils.pagination import RedisPagination
from config import PLATFORM_COLORS


async def register_luna(bot, session):

    async def membership_callback(interaction: discord.Interaction):

        luna = await fetch_luna_membership(session)

        if not luna:
            await interaction.response.send_message(
                "No membership exclusives found.",
                ephemeral=True
            )
            return

        pages = []

        for i in range(0, len(luna), 2):
            chunk = luna[i:i+2]
            desc = ""

            for g in chunk:
                desc += f"**{g['title']}**\nIncluded with Luna+\n\n"

            embed = discord.Embed(
                title="Amazon Luna Membership Exclusives",
                description=desc,
                color=PLATFORM_COLORS.get("luna")
            )

            if chunk[0].get("thumbnail"):
                embed.set_thumbnail(url=chunk[0]["thumbnail"])

            embed.set_footer(text=f"Luna • Page {i//2+1}")
            pages.append(embed)

        view = RedisPagination(pages, interaction.user.id)
        await interaction.response.send_message(embed=pages[0], view=view)

    command = app_commands.Command(
        name="membership_exclusives",
        description="Show Amazon Luna membership games",
        callback=membership_callback
    )

    bot.tree.add_command(command)

