import discord
from services.luna import fetch_luna_membership
from utils.pagination import RedisPagination
from config import GUILD_ID, PLATFORM_COLORS

async def register_luna(bot, session):

    @bot.tree.command(name="membership_exclusives", description="Amazon Luna games", guild=discord.Object(id=GUILD_ID))
    async def membership_exclusives(interaction: discord.Interaction):

        games = await fetch_luna_membership(session)

        if not games:
            await interaction.response.send_message("No Luna games found.", ephemeral=True)
            return

        pages = []
        for i in range(0, len(games), 2):
            chunk = games[i:i+2]
            desc = ""
            for g in chunk:
                desc += f"**{g['title']}**\n{g['url']}\n\n"

            embed = discord.Embed(
                title="Amazon Luna Membership",
                description=desc,
                color=PLATFORM_COLORS["luna"]
            )
            embed.set_footer(text=f"LUNA • Page {i//2+1}/{(len(games)+1)//2}")
            pages.append(embed)

        view = RedisPagination(pages, interaction.user.id)
        await interaction.response.send_message(embed=pages[0], view=view)
