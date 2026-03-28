import discord
from discord import app_commands

from services.steam import fetch_steam_discounts
from utils.pagination import RedisPagination
from constants import PLATFORM_COLORS


async def register(bot, app_state, session):

    async def discounts_callback(interaction: discord.Interaction):

        await interaction.response.defer(thinking=True)

        try:
            steam_games = await fetch_steam_discounts(session)
        except Exception as e:
            await interaction.followup.send(
                f"❌ Error fetching discounts: {e}", ephemeral=True
            )
            return

        if not steam_games:
            await interaction.followup.send(
                "No major discounts found right now.", ephemeral=True
            )
            return

        pages = []

        for i in range(0, len(steam_games), 3):
            chunk = steam_games[i:i + 3]

            embed = discord.Embed(
                title="🎮 Steam Discounts",
                color=PLATFORM_COLORS.get("steam", 0x1B2838),
            )

            for game in chunk:
                name           = game.get("name", "Unknown Game")
                discount       = game.get("discount", 0)
                final_price    = game.get("final_price", "?")
                original_price = game.get("original_price", "?")
                url            = game.get("url", "#")

                price_text    = f"💰 ~~{original_price}~~ → **{final_price}**"
                discount_text = f"🔥 **-{discount}%**" if discount else "🔥 On Sale"

                embed.add_field(
                    name=name,
                    value=f"{discount_text}\n{price_text}\n🔗 [View on Steam]({url})",
                    inline=False,
                )

            first_thumb = chunk[0].get("thumbnail") if chunk else None
            if first_thumb:
                embed.set_image(url=first_thumb)

            embed.set_footer(
                text=f"Steam • Page {i // 3 + 1} • {len(steam_games)} deals"
            )
            pages.append(embed)

        view = RedisPagination(pages, interaction.user.id)
        await interaction.followup.send(embed=pages[0], view=view)

    bot.tree.add_command(
        app_commands.Command(
            name="game_discounts",
            description="Browse current Steam discounts with pagination",
            callback=discounts_callback,
        )
    )
