import logging
import discord
from discord import app_commands

from services.free_games_service import (
    update_free_games_cache,
    get_cached_free_games
)

from config import PLATFORM_COLORS

logger = logging.getLogger("free-games-command")


# ==================================================
# REGISTER COMMAND
# ==================================================

async def register(bot, session, redis=None):

    @bot.tree.command(
        name="freegames",
        description="Show current free games"
    )
    async def freegames(interaction: discord.Interaction):

        await interaction.response.defer(thinking=True)

        games = []

        try:
            # -------------------------
            # 1. TRY CACHE FIRST
            # -------------------------
            games = await get_cached_free_games(redis)

            # -------------------------
            # 2. IF CACHE EMPTY → LIVE FETCH
            # -------------------------
            if not games:
                await update_free_games_cache(
                    session,
                    bot=bot,
                    redis=redis
                )

                games = await get_cached_free_games(redis)

        except Exception as e:
            logger.exception(
                "Freegames command failed",
                extra={"extra_data": {"error": str(e)}}
            )

            await interaction.followup.send(
                "⚠️ Failed to fetch free games.",
                ephemeral=True
            )
            return

        # -------------------------
        # NO DATA
        # -------------------------
        if not games:
            await interaction.followup.send(
                "No free games found right now.",
                ephemeral=True
            )
            return

        # -------------------------
        # LIMIT (Discord safe)
        # -------------------------
        MAX_GAMES = 10
        games = games[:MAX_GAMES]

        # -------------------------
        # SEND EMBEDS
        # -------------------------
        for game in games:

            embed = discord.Embed(
                title=game.get("title", "Unknown Title"),
                url=game.get("url"),
                color=PLATFORM_COLORS.get(
                    game.get("platform"),
                    0x2F3136  # default dark
                ),
                description=f"🎮 Free on **{game.get('platform', 'Unknown')}**"
            )

            if game.get("thumbnail"):
                embed.set_thumbnail(url=game["thumbnail"])

            # Footer UX
            embed.set_footer(
                text="Limited time offer • Grab it before it's gone!"
            )

            # Timestamp (optional)
            if game.get("end_date"):
                try:
                    embed.timestamp = discord.utils.parse_time(
                        game["end_date"]
                    )
                except Exception:
                    pass

            await interaction.followup.send(embed=embed)

        logger.info(
            "Freegames command executed",
            extra={"extra_data": {"count": len(games)}}
        )
