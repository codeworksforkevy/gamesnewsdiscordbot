# startup.py

import asyncio
import logging
import os

import discord

from events.stream_events import KNOWN_STREAMERS

logger = logging.getLogger("startup")


# ──────────────────────────────────────────────────────────────
# LIVE ROLE SETUP
# ──────────────────────────────────────────────────────────────

async def ensure_live_role(guild: discord.Guild) -> discord.Role | None:
    role = discord.utils.get(guild.roles, name="🟢 Live")
    if role:
        return role

    logger.info(f"Creating Live role in {guild.name}")
    try:
        return await guild.create_role(
            name="🟢 Live",
            color=discord.Color(0x89CFF0),
            hoist=True,
            mentionable=True,
            reason="Auto-created by Find a Curie bot",
        )
    except discord.Forbidden:
        logger.error(f"No permission to create Live role in {guild.name}")
    except Exception as e:
        logger.error(f"Live role creation failed in {guild.name}: {e}")
    return None


# ──────────────────────────────────────────────────────────────
# CHANNEL LOOKUP
# ──────────────────────────────────────────────────────────────

async def _get_announce_channel(db, guild_id: int) -> int | None:
    """Tries guild_configs first, falls back to guild_settings. Never raises."""
    for table in ("guild_configs", "guild_settings"):
        try:
            row = await db.fetchrow(
                f"SELECT announce_channel_id FROM {table} WHERE guild_id = $1",
                guild_id,
            )
            if row and row["announce_channel_id"]:
                return row["announce_channel_id"]
        except Exception:
            pass
    return None


# ──────────────────────────────────────────────────────────────
# STARTUP SYNC
# ──────────────────────────────────────────────────────────────

async def startup_sync(bot) -> None:

    logger.info("🚀 Startup sync started")

    app_state = bot.app_state
    db        = app_state.db

    if not db:
        logger.error("startup_sync: database not connected — skipping")
        return

    # ── Guild cache warmup ─────────────────────────────────────
    try:
        await asyncio.wait_for(
            asyncio.gather(*[guild.chunk() for guild in bot.guilds]),
            timeout=15,
        )
    except asyncio.TimeoutError:
        logger.warning("Guild chunking timed out — proceeding anyway")
    except Exception as e:
        logger.warning(f"Guild chunking warning: {e}")

    # ── Per-guild setup ────────────────────────────────────────
    for guild in bot.guilds:
        try:
            logger.info(f"Processing guild: {guild.name} ({guild.id})")

            channel_id = await _get_announce_channel(db, guild.id)

            if channel_id:
                logger.info(f"{guild.name} → announce channel: {channel_id} ✅")
            else:
                logger.info(
                    f"No announce channel configured for {guild.name} "
                    f"— use /live set-channel to configure"
                )

            # Live role
            try:
                live_role = await ensure_live_role(guild)
                if live_role:
                    if not hasattr(app_state, "live_roles"):
                        app_state.live_roles = {}
                    app_state.live_roles[guild.id] = live_role.id
            except Exception as e:
                logger.error(f"Live role setup failed in {guild.name}: {e}")

            # Tracked streamers
            try:
                streamers = await db.fetch(
                    "SELECT twitch_user_id, twitch_login FROM streamers WHERE guild_id = $1",
                    guild.id,
                )
                logger.info(f"{guild.name} → {len(streamers)} streamer(s) tracked")
            except Exception as e:
                logger.warning(f"Could not fetch streamers for {guild.name}: {e}")
                streamers = []

            # EventSub (optional)
            eventsub = getattr(app_state, "eventsub_manager", None)

            if eventsub:
                callback_url = (
                    os.getenv("TWITCH_EVENTSUB_CALLBACK_URL")
                    or (
                        os.getenv("PUBLIC_BASE_URL", "").rstrip("/") + "/twitch/eventsub"
                        if os.getenv("PUBLIC_BASE_URL") else None
                    )
                    or (
                        f"https://{os.getenv('RAILWAY_PUBLIC_DOMAIN')}/eventsub"
                        if os.getenv("RAILWAY_PUBLIC_DOMAIN") else None
                    )
                )

                if not callback_url:
                    logger.warning("No EventSub callback URL configured")
                else:
                    # Build subscription list: DB rows take priority,
                    # then fill in any KNOWN_STREAMERS not yet in the DB.
                    db_logins = {s["twitch_login"]: s["twitch_user_id"] for s in streamers}
                    to_subscribe: dict[str, str] = {}

                    # Add all DB streamers
                    for login, uid in db_logins.items():
                        if uid:
                            to_subscribe[uid] = login

                    # Add KNOWN_STREAMERS that aren't in the DB yet
                    for login, uid in KNOWN_STREAMERS.items():
                        if uid and login not in db_logins:
                            to_subscribe[uid] = login
                            logger.info(
                                f"Known streamer not in DB — subscribing anyway: {login}"
                            )

                    for uid, login in to_subscribe.items():
                        try:
                            await eventsub.ensure_subscriptions(uid, callback_url)
                            logger.info(f"EventSub subscribed: {login}")
                        except Exception as e:
                            logger.warning(f"EventSub failed for {login}: {e}")
            else:
                logger.info("EventSub not configured — using StreamMonitor polling")

        except Exception as e:
            logger.error(
                f"Startup error in guild {guild.id} ({guild.name}): {e}",
                exc_info=True,
            )

    logger.info("✅ Startup sync completed")
