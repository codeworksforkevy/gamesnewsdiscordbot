# commands/free_games.py

import logging
import discord
from discord import app_commands
from datetime import datetime

from services.free_games_service import get_cached_free_games

logger = logging.getLogger("free-games-command")

# Senin sevdiğin Soft Pink rengi
KEVY_PINK = 0xFFB6C1

# Platformların yan renkleri (Embed içinde küçük vurgular için kullanılabilir)
PLATFORM_EMOJIS = {
    "epic": "🎮",
    "steam": "☁️",
    "gog": "💜",
    "humble": "❤️",
    "luna": "🌙",
    "amazon": "📦"
}

class ClaimView(discord.ui.View):
    """Oyun sayfasina giden şık bir buton."""
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
            # Önbellekteki tüm bedava oyunları getir
            games = await get_cached_free_games(app_state.cache)
        except Exception as e:
            logger.error(f"Free games fetch failed: {e}")
            return await interaction.followup.send("❌ An error occurred while fetching laboratory records.")

        if not games:
            return await interaction.followup.send("🧪 The lab is empty. No free experiments found right now.")

        # En fazla 10 oyun göster (Discord limiti)
        for game in games[:10]:
            title = game.get("title", "Unknown Experiment")
            url = game.get("url", "")
            platform = game.get("platform", "Unknown").lower()
            thumb = game.get("thumbnail")
            
            # Embed Tasarımı (Kevy Stili)
            embed = discord.Embed(
                title=f"{PLATFORM_EMOJIS.get(platform, '🎁')} {title}",
                url=url if url else None,
                color=KEVY_PINK, # Ana renk her zaman pembe
                description=f"👩‍🔬 **Curie's Lab Report:**\nThis experiment is now **FREE** to claim on **{platform.upper()}**!"
            )

            if thumb:
                embed.set_image(url=thumb)

            # Bitiş tarihi varsa ekle
            end_date = game.get("end_date") or game.get("end_time")
            if end_date:
                try:
                    dt = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
                    embed.set_footer(text="Limited time offer • Expires")
                    embed.timestamp = dt
                except:
                    embed.set_footer(text="🧪 Grab it before the experiment ends!")
            else:
                embed.set_footer(text="🧪 Stay Zen • Available now")

            # Buton ekle
            view = ClaimView(url, platform) if url else None
            
            await interaction.followup.send(embed=embed, view=view)

    logger.info("Command /free_games registered with Soft Pink UX")
