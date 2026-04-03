# commands/clip_of_day.py
#
# 🎬 Clip of the Day — Suggestion #6
#
# Two features:
#   /clip <streamer>     → fetch the top clip of the past 7 days on demand
#   Background task      → daily at midnight UTC, posts top clip from
#                          each tracked streamer to the announce channel

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
            params["started_at"] = (
                datetime.now(timezone.utc) - timedelta(days=days)
            ).strftime("%Y-%m-%dT%H:%M:%SZ")
            params["ended_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        data = await api.request("clips", params=params)

        if not data or not data.get("data"):
            return None

        # Date guard — only applies when a window is set
        clip_raw     = data["data"][0]
        clip_created = clip_raw.get("created_at", "")
        if days is not None and clip_created:
            try:
                cutoff  = datetime.now(timezone.utc) - timedelta(days=days)
                clip_dt = datetime.fromisoformat(clip_created.replace("Z", "+00:00"))
                if clip_dt < cutoff:
                    return None
            except Exception:
                pass

        clip = data["data"][0]
        return {
            "title":        clip.get("title", "Untitled"),
            "url":          clip.get("url", ""),
            "thumbnail":    clip.get("thumbnail_url", ""),
            "view_count":   clip.get("view_count", 0),
            "duration":     clip.get("duration", 0),
            "creator":      clip.get("creator_name", "Unknown"),
            "created_at":   clip.get("created_at", ""),
            "broadcaster":  clip.get("broadcaster_name", user_login),
            "game":         clip.get("game_id", ""),
            "profile_image": user.get("profile_image_url", ""),
        }
    except Exception as e:
        logger.warning(f"Clip fetch failed for {user_login}: {e}")
        return None


def _build_clip_embed(clip: dict, user_login: str, daily: bool = False) -> discord.Embed:
    """
    daily=True  → posted by the background task (Clip of the Day)
    daily=False → posted by /clip command (user-requested)
    """
    duration_str = f"{int(clip['duration'])}s"
    if clip["duration"] >= 60:
        m, s = divmod(int(clip["duration"]), 60)
        duration_str = f"{m}m {s}s"

    created_ts = ""
    if clip.get("created_at"):
        try:
            dt = datetime.fromisoformat(clip["created_at"].replace("Z", "+00:00"))
            created_ts = f"<t:{int(dt.timestamp())}:R>"
        except Exception:
            pass

    embed = discord.Embed(
        title=f"🎬 {clip['title']}",
        url=clip["url"],
        color=0x003153,  # navy
    )

    # Author: "streamer's Clip of the Day" or "streamer's top clip"
    author_label = (
        f"{clip['broadcaster']}'s Clip of the Day"
        if daily else
        f"{clip['broadcaster']}'s top clip"
    )
    embed.set_author(
        name=author_label,
        url=f"https://twitch.tv/{user_login}",
        icon_url=clip.get("profile_image", ""),
    )

    embed.add_field(name="Total views", value=f"{clip['view_count']:,}", inline=True)
    embed.add_field(name="Length",      value=duration_str,             inline=True)
    embed.add_field(name="Clipped by",  value=clip["creator"],          inline=True)

    if created_ts:
        embed.add_field(name="Clipped", value=created_ts, inline=True)

    if clip.get("thumbnail"):
        embed.set_image(url=clip["thumbnail"])

    embed.set_footer(text="🎬 Find a Curie")
    embed.timestamp = discord.utils.utcnow()

    return embed


# ──────────────────────────────────────────────────────────────
# DAILY TASK
# ──────────────────────────────────────────────────────────────

async def _clip_of_day_loop(bot, app_state):
    """Posts the top clip of the week for each tracked streamer, daily at midnight UTC."""
    await bot.wait_until_ready()
    logger.info("🎬 Clip-of-day loop started")

    while True:
        # Sleep until next midnight UTC
        now        = datetime.now(timezone.utc)
        tomorrow   = (now + timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        sleep_secs = (tomorrow - now).total_seconds()
        logger.info(f"🎬 Next clip-of-day post in {sleep_secs/3600:.1f}h")
        await asyncio.sleep(sleep_secs)

        try:
            await _post_daily_clips(bot, app_state)
        except Exception as e:
            logger.error(f"🎬 Daily clip task failed: {e}", exc_info=True)


async def _streamed_today(api, user_login: str) -> bool:
    """
    Returns True if the streamer had a VOD created in the past 24 hours.
    Uses /videos with type=archive and checks created_at manually —
    the Twitch API does not support date-based filtering on /videos directly.
    """
    try:
        user = await api.get_user_by_login(user_login)
        if not user:
            return False

        data = await api.request(
            "videos",
            params={
                "user_id": user["id"],
                "type":    "archive",
                "first":   5,
            },
        )
        if not data or not data.get("data"):
            return False

        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        for vod in data["data"]:
            created_str = vod.get("created_at", "")
            if not created_str:
                continue
            try:
                created = datetime.fromisoformat(created_str.replace("Z", "+00:00"))
                if created >= cutoff:
                    return True
            except Exception:
                continue
        return False
    except Exception:
        return False


async def _post_daily_clips(bot, app_state):
    """
    Posts the top clip of the day — but ONLY if the streamer actually
    streamed in the past 24 hours. No stream = no clip post.
    """
    db  = app_state.db
    api = app_state.twitch_api

    if not api:
        return

    try:
        rows = await db.fetch(
            "SELECT DISTINCT twitch_user_id, twitch_login FROM streamers"
        )
    except Exception as e:
        logger.error(f"🎬 DB fetch failed: {e}")
        return

    from db.guild_settings import get_guild_config

    for row in rows:
        login = row["twitch_login"]

        # Only post if they actually streamed today
        had_stream = await _streamed_today(api, login)
        if not had_stream:
            logger.info(f"🎬 {login} didn't stream today — skipping clip")
            continue

        clip = await _fetch_top_clip(api, login, days=1)  # just today's clips
        if not clip or not clip["url"]:
            logger.info(f"🎬 No clip found for {login} today — skipping")
            continue

        embed = _build_clip_embed(clip, login, daily=True)

        for guild in bot.guilds:
            try:
                config = await get_guild_config(guild.id)
                if not config:
                    continue

                channel_id = config.get("announce_channel_id")
                if not channel_id:
                    continue

                channel = guild.get_channel(channel_id) or await bot.fetch_channel(channel_id)
                if channel:
                    await channel.send(embed=embed)
                    logger.info(f"🎬 Posted today's top clip for {login} in {guild.name}")
            except Exception as e:
                logger.warning(f"🎬 Failed to post clip in guild {guild.id}: {e}")

        await asyncio.sleep(1)


# ──────────────────────────────────────────────────────────────
# REGISTER
# ──────────────────────────────────────────────────────────────

async def register(bot, app_state, session):

    # Start background daily task — registered via on_ready so bot is fully initialised
    @bot.listen("on_ready")
    async def _start_clip_loop():
        if not any(t.get_name() == "clip-of-day" for t in asyncio.all_tasks()):
            asyncio.create_task(_clip_of_day_loop(bot, app_state), name="clip-of-day")

    @bot.tree.command(
        name="clip",
        description="🎬 Show the top clip from a tracked streamer",
    )
    @app_commands.describe(
        streamer="Twitch username",
        period="Time period to look in (default: this week)",
    )
    @app_commands.choices(period=[
        app_commands.Choice(name="This week",   value="week"),
        app_commands.Choice(name="This month",  value="month"),
        app_commands.Choice(name="All time",    value="all"),
    ])
    async def clip_command(
        interaction: discord.Interaction,
        streamer: str,
        period: str = "week",
    ):
        await interaction.response.defer()

        login = streamer.strip().lower()

        # Verify streamer is tracked in this server
        try:
            row = await app_state.db.fetchrow(
                "SELECT 1 FROM streamers WHERE twitch_login = $1 AND guild_id = $2",
                login, interaction.guild_id,
            )
            if not row:
                rows = await app_state.db.fetch(
                    "SELECT twitch_login FROM streamers WHERE guild_id = $1 ORDER BY twitch_login",
                    interaction.guild_id,
                )
                names = ", ".join(f"`{r['twitch_login']}`" for r in rows) or "none yet"
                await interaction.followup.send(
                    f"❌ **{login}** is not in the tracked list for this server.\n"
                    f"Tracked streamers: {names}",
                    ephemeral=True,
                )
                return
        except Exception as e:
            logger.warning(f"/clip DB check failed: {e}")

        # Map period to days (or None for all time)
        period_days = {"week": 7, "month": 30, "all": None}
        days = period_days.get(period, 7)

        clip = await _fetch_top_clip(app_state.twitch_api, login, days=days)

        if not clip:
            period_label = {"week": "this week", "month": "this month", "all": "all time"}[period]
            await interaction.followup.send(
                f"😔 No clips found for **{login}** ({period_label}).\n"
                f"They may not have any clips in this period.",
                ephemeral=True,
            )
            return

        embed = _build_clip_embed(clip, login)
        await interaction.followup.send(embed=embed)
        logger.info(f"/clip {login} period={period} — found: {clip['title']}")
