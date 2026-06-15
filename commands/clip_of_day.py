# commands/clip_of_day.py
#
# 🎬 Clip of the Day — Suggestion #6
#
# /clip <streamer> → fetch the top clip of the specified period on demand

import asyncio
import logging
from datetime import datetime, timezone, timedelta

import discord
from discord import app_commands

logger = logging.getLogger("clip-of-day")


# ──────────────────────────────────────────────────────────────
# HELPERS
# ──────────────────────────────────────────────────────────────

async def _fetch_top_clip(api, user_login: str, days: int | None = 7) -> dict | None:
    """
    Fetch the top clip for a streamer in the past N days.
    Returns None if no clip was created within the time window.
    """
    try:
        user = await api.get_user_by_login(user_login)
        if not user:
            return None

        # Build params — days=None means all time (no date filter)
        params: dict = {"broadcaster_id": user["id"], "first": 1}
        
        if days is not None:
            now = datetime.now(timezone.utc)
            params["started_at"] = (now - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
            params["ended_at"] = now.strftime("%Y-%m-%dT%H:%M:%SZ")

        data = await api.request("clips", params=params)

        if data and "data" in data and len(data["data"]) > 0:
            return data["data"][0]
        
        return None
    except Exception as e:
        logger.error(f"Error fetching top clip: {e}")
        return None


def _build_clip_embed(clip: dict, login: str) -> discord.Embed:
    """Constructs the embed for the clip with a clean UX."""
    embed = discord.Embed(
        title=clip.get('title', 'Top Clip'),
        url=clip.get('url'),
        color=0x9146FF  # Official Twitch Purple
    )
    
    embed.set_author(name=clip.get('creator_name', 'Unknown Creator'))
    
    thumb_url = clip.get('thumbnail_url', '')
    if thumb_url:
        embed.set_image(url=thumb_url)
        
    views = clip.get('view_count', 0)
    embed.add_field(name="👁️ Views", value=f"{views:,}", inline=True)
    
    embed.set_footer(text=f"Clipped from twitch.tv/{login}")
    embed.timestamp = discord.utils.utcnow()
    
    return embed


# ──────────────────────────────────────────────────────────────
# COGS & COMMANDS
# ──────────────────────────────────────────────────────────────

async def register(bot, app_state, session):
    @bot.tree.command(name="clip", description="Shows the most popular clip of a specific streamer.")
    @app_commands.choices(period=[
        app_commands.Choice(name="This Week", value="week"),
        app_commands.Choice(name="This Month", value="month"),
        app_commands.Choice(name="All Time", value="all"),
    ])
    async def clip_cmd(interaction: discord.Interaction, streamer: str, period: str = "week"):
        await interaction.response.defer(ephemeral=False)
        login = streamer.strip().lower()

        # Safely acquire a DB connection to check if the streamer is tracked
        try:
            async with app_state.db.pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT 1 FROM streamers WHERE twitch_login = $1 AND guild_id = $2",
                    login, interaction.guild_id
                )
                
                # If the streamer is not found in the DB, fetch the list of tracked streamers to guide the user
                if not row:
                    rows = await conn.fetch(
                        "SELECT twitch_login FROM streamers WHERE guild_id = $1 ORDER BY twitch_login",
                        interaction.guild_id
                    )
                    names = ", ".join(f"`{r['twitch_login']}`" for r in rows) or "none yet"
                    await interaction.followup.send(
                        f"❌ **{login}** is not in the tracked list for this server.\n"
                        f"Tracked streamers: {names}",
                        ephemeral=True
                    )
                    return
        except Exception as e:
            logger.error(f"/clip DB error: {e}")
            await interaction.followup.send("❌ A database error occurred while verifying the streamer.", ephemeral=True)
            return

        # Map the selected period to days (None means no date filter/all time)
        period_days = {"week": 7, "month": 30, "all": None}
        days = period_days.get(period, 7)

        # Fetch the clip from Twitch API
        clip = await _fetch_top_clip(app_state.twitch_api, login, days=days)

        if not clip:
            period_label = {"week": "this week", "month": "this month", "all": "all time"}[period]
            await interaction.followup.send(
                f"😔 No clips found for **{login}** ({period_label}).\n"
                f"They may not have any clips generated within this time frame.",
                ephemeral=True
            )
            return

        # Build and send the final embed
        embed = _build_clip_embed(clip, login)
        await interaction.followup.send(embed=embed)
        
        logger.info(f"/clip command successfully executed by {interaction.user} for {login}")

    logger.info("clip command registered")
