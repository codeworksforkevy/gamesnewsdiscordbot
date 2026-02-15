import discord
from services.steam import fetch_steam_discounts
from utils.pagination import RedisPagination
from config import GUILD_ID, PLATFORM_COLORS

async def register_discounts(bot, session):

    @bot.tree.command(name="game_discounts", description="Steam discounts", guild=discord.Object(id=GUILD_ID))
    async def game_discounts(interaction: discord.Interaction):

        games = await fetch_steam_discounts(session)

        if not games:
            await interaction.response.send_message("No discounts found.", ephemeral=True)
            return

        pages = []
        for i in range(0, len(games), 2):
            chunk = games[i:i+2]
            desc = ""
            for g in chunk:
                desc += f"**{g['title']}** — {g['discount']}% OFF\n{g['url']}\n\n"

            embed = discord.Embed(
                title="Steam Discounts",
                description=desc,
                color=PLATFORM_COLORS["steam"]
            )
            embed.set_footer(text=f"STEAM • Page {i//2+1}/{(len(games)+1)//2}")
            pages.append(embed)

        view = RedisPagination(pages, interaction.user.id)
        await interaction.response.send_message(embed=pages[0], view=view)
