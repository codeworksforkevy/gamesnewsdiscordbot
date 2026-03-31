# commands/free_games.py

import logging
import discord
from discord import app_commands
from datetime import datetime
from services.free_games_service import get_cached_free_games

logger = logging.getLogger("free-games-command")

# Senin sevdiğin Soft Pink rengi
KEVY_PINK = 0xFFB6C1

class ClaimView(discord.ui.View):
    def __init__(self, url: str, platform: str):
        super().__init__(timeout=None)
        self.add_item(
            discord.ui.Button(
                label=f"Claim on {platform.capitalize()}",
                url=url,
                style=discord.ButtonStyle.link,
            )
        )

async def register(bot, app_state, session):
    
    @bot.tree.command(name="free_games", description="Show currently available free games")
    async def free_games(interaction: discord.Interaction):
        await interaction.response.defer(thinking=True)

        try:
            games = await get_cached_free_games(app_state.cache)
        except Exception as e:
            logger.error(f"Free games fetch failed: {e}")
            return await interaction.followup.send("❌ Error fetching data.")

        if not games:
            return await interaction.followup.send("No free games found right now.")

        for game in games[:10]:
            title = game.get("title", "Unknown Title")
            url = game.get("url", "")
            platform = game.get("platform", "Unknown").capitalize()
            thumb = game.get("thumbnail")
            
            # Sade ve şık Embed Tasarımı
            embed = discord.Embed(
                title=title,
                url=url if url else None,
                color=KEVY_PINK,
                description=f"Free on **{platform}**" # Sadeleştirilmiş açıklama
            )

            if thumb:
                embed.set_image(url=thumb)

            # Bitiş tarihi kontrolü
            end_date = game.get("end_date") or game.get("end_time")
            if end_date:
                try:
                    dt = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
                    embed.set_footer(text="Offer ends")
                    embed.timestamp = dt
                except:
                    pass
            else:
                embed.set_footer(text=f"{platform} • Free Game")

            view = ClaimView(url, platform) if url else None
            await interaction.followup.send(embed=embed, view=view)

    logger.info("Command /free_games registered with minimalist Soft Pink UX")
