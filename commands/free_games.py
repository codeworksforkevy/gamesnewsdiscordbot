# commands/free_games.py
#
# FIX: register(bot, session, redis=None) was wrong — command_loader
# calls register(bot, app_state, session), so app_state was being passed
# as session, causing 'AppState' object has no attribute 'get' on every
# HTTP request to Epic and GOG.
#
# Also added: Claim now link buttons on each game embed.

import logging
import discord
from discord import app_commands

from services.free_games_service import (
    update_free_games_cache,
    get_cached_free_games,
)
from config import PLATFORM_COLORS

logger = logging.getLogger("free-games-command")


# ==================================================
# CLAIM BUTTON VIEW
# ==================================================

class ClaimView(discord.ui.View):
    """Link button that takes users straight to the store page."""
    def __init__(self, url: str, platform: str = ""):
        super().__init__(timeout=None)
        label = f"🎮 Claim on {platform}" if platform else "🎮 Claim now"
        self.add_item(
            discord.ui.Button(
                label=label,
                url=url,
                style=discord.ButtonStyle.link,
            )
        )


# ==================================================
# REGISTER
# ==================================================

async def register(bot, app_state, session):
    """
    FIX: signature is now (bot, app_state, session) to match
    command_loader.py which calls register(bot, app_state, session).
    Previously was (bot, session, redis=None) which caused app_state
    to be passed as session — breaking all HTTP requests.
    """

    @bot.tree.command(
        name="freegames",
        description="Show current free games from Epic, GOG and more",
    )
    async def freegames(interaction: discord.Interaction):

        await interaction.response.defer(thinking=True)

        redis = app_state.cache

        try:
            # Try cache first — only fetch live if cache is empty
            games = await get_cached_free_games(redis)

            if not games:
                await update_free_games_cache(session, redis=redis)
                games = await get_cached_free_games(redis)

        except Exception as e:
            logger.exception(f"Freegames command failed: {e}")
            await interaction.followup.send(
                "⚠️ Failed to fetch free games. Please try again in a moment.",
                ephemeral=True,
            )
            return

        if not games:
            await interaction.followup.send(
                "No free games found right now. Check back soon!",
                ephemeral=True,
            )
            return

        # Limit to 10 to avoid Discord rate limits on followup.send
        games = games[:10]

        for game in games:
            title    = game.get("title", "Unknown Title")
            url      = game.get("url", "")
            platform = game.get("platform", "Unknown")
            thumb    = game.get("thumbnail")
            end_date = game.get("end_date") or game.get("end_time", "")

            embed = discord.Embed(
                title=title,
                url=url or None,
                color=PLATFORM_COLORS.get(platform.lower(), 0x2F3136),
                description=f"🎮 Free on **{platform}**",
            )

            if thumb:
                embed.set_image(url=thumb)

            # Discord relative timestamp for expiry
            if end_date:
                try:
                    from datetime import datetime
                    dt = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
                    ts = int(dt.timestamp())
                    embed.set_footer(text=f"Free until")
                    embed.timestamp = dt
                except Exception:
                    embed.set_footer(text="Limited time offer — grab it before it's gone!")
            else:
                embed.set_footer(text="Limited time offer — grab it before it's gone!")

            # Claim button — only if we have a URL
            view = ClaimView(url, platform) if url else None

            await interaction.followup.send(embed=embed, view=view)

        logger.info(f"Freegames command: sent {len(games)} game(s)")
