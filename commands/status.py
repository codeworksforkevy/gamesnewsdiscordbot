"""
cogs/status_command.py
────────────────────────────────────────────────────────────────
/status <streamer>

Shows whether a Twitch streamer is currently live.
Pulls from Redis (instant) and falls back to Twitch metadata cache.
Response is ephemeral — only the requesting user sees it.
"""

import time
import logging

import discord
from discord import app_commands
from discord.ext import commands

from event_router import get_stream_status

logger = logging.getLogger("status_command")


class StatusCommand(commands.Cog):

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ──────────────────────────────────────────────────────────
    # /status
    # ──────────────────────────────────────────────────────────

    @app_commands.command(
        name="status",
        description="Check whether a Twitch streamer is currently live."
    )
    @app_commands.describe(streamer="Twitch username to look up")
    async def status(self, interaction: discord.Interaction, streamer: str):

        await interaction.response.defer(ephemeral=True)

        user_login = streamer.strip().lower()

        stream = await get_stream_status(user_login)

        if stream is None:
            # ── OFFLINE ─────────────────────────────────────────
            embed = discord.Embed(
                description=f"**{user_login}** is currently **offline**.",
                color=0x6e6e6e,
            )
            embed.set_footer(text=f"twitch.tv/{user_login}")
            await interaction.followup.send(embed=embed, ephemeral=True)
            return

        # ── LIVE ─────────────────────────────────────────────────
        title     = stream.get("title")     or f"{user_login} is live!"
        game      = stream.get("game_name") or "Unknown"
        thumbnail = (
            f"https://static-cdn.jtvnw.net/previews-ttv/live_user_{user_login}"
            f"-1280x720.jpg?t={int(time.time())}"
        )

        embed = discord.Embed(
            title=f"🔴  {title}",
            url=f"https://twitch.tv/{user_login}",
            color=0x9146FF,
        )

        embed.add_field(name="Status", value="**Live**",   inline=True)
        embed.add_field(name="Playing", value=game,         inline=True)
        embed.add_field(
            name="Watch",
            value=f"[twitch.tv/{user_login}](https://twitch.tv/{user_login})",
            inline=True,
        )
        embed.set_image(url=thumbnail)
        embed.set_footer(text="Live on Twitch")

        await interaction.followup.send(embed=embed, ephemeral=True)
        logger.info(f"/status used for {user_login} — live")


# ──────────────────────────────────────────────────────────────
# SETUP HOOK
# ──────────────────────────────────────────────────────────────

async def setup(bot: commands.Bot):
    await bot.add_cog(StatusCommand(bot))
    logger.info("StatusCommand cog loaded")
