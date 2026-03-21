import discord
import logging
import asyncio

logger = logging.getLogger("startup")


# ==================================================
# LIVE ROLE SETUP
# ==================================================
async def ensure_live_role(guild: discord.Guild):

    role = discord.utils.get(guild.roles, name="Live")

    if role:
        return role

    logger.info(f"Creating Live role in {guild.name}")

    try:
        return await guild.create_role(
            name="Live",
            color=discord.Color.from_rgb(137, 207, 240),
            mentionable=True
        )

    except discord.Forbidden:
        logger.error(f"Missing permissions to create role in {guild.name}")
    except Exception as e:
        logger.error(f"Role creation error in {guild.name}: {e}")

    return None


# ==================================================
# STARTUP SYNC
# ==================================================
async def startup_sync(bot):

    logger.info("🚀 Startup sync started")

    app_state = bot.app_state
    db = app_state.require_db()
    eventsub = app_state.eventsub_manager

    # =========================
    # GUILD CACHE WARMUP
    # =========================
    try:
        await asyncio.wait_for(
            asyncio.gather(*[guild.chunk() for guild in bot.guilds]),
            timeout=10
        )
    except Exception as e:
        logger.warning(f"Guild chunking warning: {e}")

    # =========================
    # GUILD LOOP
    # =========================
    for guild in bot.guilds:

        try:
            logger.info(f"Processing guild: {guild.name} ({guild.id})")

            # =========================
            # LOAD SETTINGS FROM DB
            # =========================
            settings = await db.fetchrow(
                """
                SELECT announce_channel_id
                FROM guild_settings
                WHERE guild_id = $1
                """,
                guild.id
            )

            if not settings:
                logger.warning(f"No settings found for guild {guild.id}")
                continue

            channel_id = settings["announce_channel_id"]

            if not channel_id:
                logger.warning(f"No announce channel for guild {guild.id}")
                continue

            # =========================
            # ENSURE LIVE ROLE
            # =========================
            live_role = await ensure_live_role(guild)

            if live_role:
                if not hasattr(app_state, "live_roles"):
                    app_state.live_roles = {}

                app_state.live_roles[guild.id] = live_role.id

            # =========================
            # SAVE STATE
            # =========================
            await app_state.emit(
                "guild_ready",
                {
                    "guild_id": guild.id,
                    "channel_id": channel_id,
                    "live_role_id": getattr(live_role, "id", None),
                }
            )

            # =========================
            # FETCH STREAMERS
            # =========================
            streamers = await db.fetch(
                """
                SELECT twitch_user_id, twitch_login
                FROM streamers
                WHERE guild_id = $1
                """,
                guild.id
            )

            logger.info(f"{guild.name} → {len(streamers)} streamer(s) found")

            # =========================
            # EVENTSUB SUBSCRIPTIONS
            # =========================
            if not eventsub:
                logger.warning("EventSub manager not available")
                continue

            for s in streamers:

                broadcaster_id = s["twitch_user_id"]
                twitch_login = s["twitch_login"]

                try:
                    await eventsub.subscribe_stream_online(
                        broadcaster_id,
                        app_state.get_config("webhook_url")
                    )

                    logger.info(f"Subscribed: {twitch_login}")

                except Exception as e:
                    logger.error(
                        f"Subscription failed ({twitch_login})",
                        extra={"error": str(e)}
                    )

                # =========================
                # EVENT EMIT
                # =========================
                await app_state.emit(
                    "streamer_subscribed",
                    {
                        "guild_id": guild.id,
                        "twitch_login": twitch_login,
                        "broadcaster_id": broadcaster_id,
                    }
                )

        except Exception as e:
            logger.error(
                f"Startup error in guild {guild.id}",
                extra={"error": str(e)}
            )

    # =========================
    # READY EVENT
    # =========================
    app_state.mark_ready()

    logger.info("✅ Startup sync completed")
