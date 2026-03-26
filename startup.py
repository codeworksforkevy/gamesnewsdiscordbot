# startup.py
#
# FIX 1: Was calling app_state.require_db() which returns the Database
#         object — then calling .fetchrow() on it which didn't exist.
#         Now uses app_state.db.fetchrow() directly.
# FIX 2: eventsub_manager is None in most setups — was crashing the
#         entire guild loop when it wasn't available. Now continues
#         gracefully without EventSub if it isn't configured.
# FIX 3: Errors in one guild no longer silently swallow the exception
#         detail — full message is now logged.

import discord
import logging
import asyncio

logger = logging.getLogger("startup")


# ==================================================
# LIVE ROLE SETUP
# ==================================================

async def ensure_live_role(guild: discord.Guild) -> discord.Role | None:
    role = discord.utils.get(guild.roles, name="Live")
    if role:
        return role

    logger.info(f"Creating Live role in {guild.name}")
    try:
        return await guild.create_role(
            name="Live",
            color=discord.Color.from_rgb(145, 70, 255),
            mentionable=True,
            reason="Auto-created by Find a Curie bot",
        )
    except discord.Forbidden:
        logger.error(f"No permission to create Live role in {guild.name}")
    except Exception as e:
        logger.error(f"Live role creation failed in {guild.name}: {e}")
    return None


# ==================================================
# STARTUP SYNC
# ==================================================

async def startup_sync(bot) -> None:

    logger.info("🚀 Startup sync started")

    app_state = bot.app_state
    db        = app_state.db   # FIX: use db directly, not require_db()

    if not db:
        logger.error("startup_sync: database not connected — skipping")
        return

    # ── Guild cache warmup ─────────────────────────────────────────────────
    try:
        await asyncio.wait_for(
            asyncio.gather(*[guild.chunk() for guild in bot.guilds]),
            timeout=15,
        )
    except asyncio.TimeoutError:
        logger.warning("Guild chunking timed out — proceeding anyway")
    except Exception as e:
        logger.warning(f"Guild chunking warning: {e}")

    # ── Per-guild setup ────────────────────────────────────────────────────
    for guild in bot.guilds:
        try:
            logger.info(f"Processing guild: {guild.name} ({guild.id})")

            # Load settings — check both table names (legacy + new)
            settings = await db.fetchrow(
                """
                SELECT announce_channel_id FROM guild_configs
                WHERE guild_id = $1
                """,
                guild.id,
            )

            if not settings:
                # Try legacy table
                settings = await db.fetchrow(
                    """
                    SELECT announce_channel_id FROM guild_settings
                    WHERE guild_id = $1
                    """,
                    guild.id,
                )

            if not settings or not settings["announce_channel_id"]:
                logger.info(
                    f"No announce channel configured for {guild.name} — "
                    f"use /live set-channel to configure"
                )
                # Don't skip — still ensure Live role exists
            else:
                logger.info(
                    f"{guild.name} → announce channel: {settings['announce_channel_id']}"
                )

            # Ensure Live role exists
            live_role = await ensure_live_role(guild)
            if live_role:
                if not hasattr(app_state, "live_roles"):
                    app_state.live_roles = {}
                app_state.live_roles[guild.id] = live_role.id

            # Fetch tracked streamers
            streamers = await db.fetch(
                """
                SELECT twitch_user_id, twitch_login
                FROM streamers
                WHERE guild_id = $1
                """,
                guild.id,
            )

            logger.info(f"{guild.name} → {len(streamers)} streamer(s) tracked")

            # ── EventSub subscriptions (optional) ─────────────────────────
            eventsub = getattr(app_state, "eventsub_manager", None)

            if eventsub:
                for s in streamers:
                    broadcaster_id = s["twitch_user_id"]
                    twitch_login   = s["twitch_login"]
                    try:
                        webhook_url = app_state.get_config("webhook_url")
                        await eventsub.subscribe_stream_online(
                            broadcaster_id, webhook_url
                        )
                        logger.info(f"EventSub subscribed: {twitch_login}")
                    except Exception as e:
                        logger.warning(
                            f"EventSub subscription failed for {twitch_login}: {e}"
                        )
            else:
                logger.info(
                    "EventSub manager not configured — "
                    "using StreamMonitor polling instead"
                )

        except Exception as e:
            logger.error(
                f"Startup error in guild {guild.id} ({guild.name}): {e}",
                exc_info=True,
            )

    logger.info("✅ Startup sync completed")
