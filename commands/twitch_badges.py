
import discord
from discord import app_commands
from services.twitch import fetch_official_global_badges
from utils.pagination import RedisPagination
from config import PLATFORM_COLORS


async def register_twitch_badges(bot, session):

    async def badges_callback(interaction: discord.Interaction):

        await interaction.response.defer(thinking=True)

        try:
            badges = await fetch_official_global_badges(session)
        except Exception as e:
            await interaction.followup.send(
                f"Error fetching Twitch badges: {str(e)}",
                ephemeral=True
            )
            return

        if not badges:
            await interaction.followup.send(
                "No Twitch global badges found.",
                ephemeral=True
            )
            return

        pages = []

        for i in range(0, len(badges), 4):
            chunk = badges[i:i+4]
            desc_block = ""

            for badge in chunk:
                desc_block += f"**{badge['set_id'].capitalize()}**\n\n"

            embed = discord.Embed(
                title="👩‍💻 Global Badges",
                description=desc_block.strip(),
                color=PLATFORM_COLORS.get("twitch", 0x9146FF)
            )

            # First badge thumbnail as page thumbnail
            embed.set_thumbnail(url=chunk[0]["thumbnail"])

            embed.set_footer(
                text=f"Twitch • Page {i//4+1}/{(len(badges)+3)//4}"
            )

            pages.append(embed)

        view = RedisPagination(pages, interaction.user.id)

        try:
            bot.tree.remove_command("twitch_badges")
        except Exception:
            pass

        await interaction.followup.send(
            embed=pages[0],
            view=view
        )

    command = app_commands.Command(
        name="twitch_badges",
        description="Show official Twitch global badges",
        callback=badges_callback
    )

    try:
        bot.tree.remove_command("twitch_badges")
    except Exception:
        pass

    bot.tree.add_command(command)
