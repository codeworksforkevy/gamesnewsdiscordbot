import discord
from services.twitch import fetch_twitch_badges
from utils.pagination import RedisPagination
from config import GUILD_ID, PLATFORM_COLORS

async def register_twitch_badges(bot, session):

    @bot.tree.command(name="twitch_badges", description="Latest Twitch badges", guild=discord.Object(id=GUILD_ID))
    async def twitch_badges(interaction: discord.Interaction):

        badges = await fetch_twitch_badges(session)

        if not badges:
            await interaction.response.send_message("No badges found.", ephemeral=True)
            return

        pages = []
        for i in range(0, len(badges), 2):
            chunk = badges[i:i+2]
            desc = ""
            for b in chunk:
                desc += f"**{b['title']}**\n{b['description']}\n\n"

            embed = discord.Embed(
                title="Twitch Badges",
                description=desc,
                color=PLATFORM_COLORS["twitch"]
            )
            embed.set_footer(text=f"TWITCH • Page {i//2+1}/{(len(badges)+1)//2}")
            pages.append(embed)

        view = RedisPagination(pages, interaction.user.id)
        await interaction.response.send_message(embed=pages[0], view=view)
