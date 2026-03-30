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

async def _fetch_top_clip(api, user_login: str, days: int = 7) -> dict | None:
    """Fetch the top clip for a streamer in the past N days."""
    try:
        user = await api.get_user_by_login(user_login)
        if not user:
            return None

        started_at = (
            datetime.now(timezone.utc) - timedelta(days=days)
        ).strftime("%Y-%m-%dT%H:%M:%SZ")

        data = await api.request(
            "clips",
            params={
                "broadcaster_id": user["id"],
                "first":           1,
                "started_at":      started_at,
            },
        )

        if not data or not data.get("data"):
            return None

        clip = data["data"][0]
        return {
            "title":         clip.get("title", "Untitled"),
            "url":           clip.get("url", ""),
            "thumbnail":     clip.get("thumbnail_url", ""),
            "view_count":    clip.get("view_count", 0),
            "duration":      clip.get("duration", 0),
            "creator":       clip.get("creator_name", "Unknown"),
            "created_at":    clip.get("created_at", ""),
            "broadcaster":   clip.get("broadcaster_name", user_login),
            "game":          clip.get("game_id", ""),
            "profile_image": user.get("profile_image_url", ""),
        }
    except Exception as e:
        logger.warning(f"Clip fetch failed for {user_login}: {e}")
        return None


def _build_clip_embed(clip: dict, user_login: str) -> discord.Embed:
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
        color=0x9146FF,
    )

    embed.set_author(
        name=f"{clip['broadcaster']}'s Top Clip",
        url=f"https://twitch.tv/{user_login}",
        icon_url=clip.get("profile_image", ""),
    )

    embed.add_field(name="👀 Views",    value=f"{clip['view_count']:,}", inline=True)
    embed.add_field(name="⏱️ Duration", value=duration_str,               inline=True)
    embed.add_field(name="✂️ Clipped by", value=clip["creator"],           inline=True)

    if created_ts:
        embed.add_field(name="📅 Clipped", value=created_ts, inline=True)

    if clip.get("thumbnail"):
        embed.set_image(url=clip["thumbnail"])

    embed.set_footer(text="🎬 Clip of the Day • Find a Curie")
    embed.timestamp = discord.utils.utcnow()

    return embed


# ──────────────────────────────────────────────────────────────
# DAILY TASK
# ──────────────────────────────────────────────────────────────

async def _clip_of_day_loop(bot, app_state):
    """Posts the top clip of the week for each tracked streamer, daily at midnight UTC."""
    
    # KRİTİK DÜZELTME: Botun tamamen hazır olduğundan emin olana kadar döngüyü başlatma.
    try:
        await bot.wait_until_ready()
    except Exception as e:
        logger.error(f"🎬 Loop failed to initialize: {e}")
        return

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


async def _post_daily_clips(bot, app_state):
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
        clip  = await _fetch_top_clip(api, login, days=7)

        if not clip or not clip["url"]:
            logger.info(f"🎬 No clip found for {login} — skipping")
            continue

        embed = _build_clip_embed(clip, login)

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
                    logger.info(f"🎬 Posted clip for {login} in {guild.name}")
            except Exception as e:
                logger.warning(f"🎬 Failed to post clip in guild {guild.id}: {e}")

        await asyncio.sleep(1)  # be gentle with Discord rate limits


# ──────────────────────────────────────────────────────────────
# REGISTER
# ──────────────────────────────────────────────────────────────

async def register(bot, app_state, session):
    """Register commands and start the background task safely."""

    # DÜZELTME: Görevi doğrudan başlatmak yerine, botun döngüsüne (loop) güvenli bir şekilde ekliyoruz.
    # Bu yöntem, 'RuntimeError: Client has not been properly initialised' hatasını engeller.
    async def _safe_start():
        await bot.wait_until_ready()
        await _clip_of_day_loop(bot, app_state)

    bot.loop.create_task(_safe_start())

    @bot.tree.command(
        name="clip",
        description="🎬 Show the top Twitch clip from a streamer this week",
    )
    @app_commands.describe(
        streamer="Twitch username (e.g. ninja)",
        days="How many days to look back (1–30, default 7)",
    )
    async def clip_command(
        interaction: discord.Interaction,
        streamer: str,
        days: int = 7,
    ):
        await interaction.response.defer()

        days = max(1, min(30, days))
        login = streamer.strip().lower()

        clip = await _fetch_top_clip(app_state.twitch_api, login, days=days)

        if not clip:
            await interaction.followup.send(
                f"😔 No clips found for **{login}** in the past {days} day(s).\n"
                f"They may not have any clips yet, or the name is misspelled.",
                ephemeral=True,
            )
            return

        embed = _build_clip_embed(clip, login)
        await interaction.followup.send(embed=embed)
        logger.info(f"/clip {login} ({days}d) — found: {clip['title']}")
