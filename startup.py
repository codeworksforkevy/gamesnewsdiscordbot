import discord
import logging
import asyncio

logger = logging.getLogger("startup")


# ==================================================
# LIVE ROLE SETUP
# ==================================================

async def ensure_live_role(guild: discord.Guild):

    # "Live" rolünü bul
    role = discord.utils.get(guild.roles, name="Live")

    if role:
        return role

    logger.info(f"Creating Live role in {guild.name}")

    try:
        return await guild.create_role(
            name="Live",
            color=discord.Color.from_rgb(137, 207, 240),  # Baby Blue
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

    db = bot.app_state.db
    eventsub = bot.app_state.eventsub_manager

    # Guild'leri yükle (cache warm-up)
    await asyncio.gather(*[guild.chunk() for guild in bot.guilds])

    for guild in bot.guilds:

        try:
            # 1. LIVE ROLE garanti
            live_role = await ensure_live_role(guild)

            # 2. DB streamer'ları çek
            streamers = await db.fetch(
                "SELECT twitch_user_id, twitch_login FROM streamers WHERE guild_id=$1",
                guild.id
            )

            logger.info(f"{guild.name} → {len(streamers)} streamer found")

            # 3. EventSub tekrar subscribe et
            for s in streamers:

                broadcaster_id = s["twitch_user_id"]
                twitch_login = s["twitch_login"]

                try:
                    await eventsub.subscribe_stream_online(
                        broadcaster_id,
                        bot.app_state.webhook_url
                    )

                    logger.info(f"Subscribed: {twitch_login}")

                except Exception as e:
                    logger.error(f"Subscription failed ({twitch_login}): {e}")

            # 4. Live role cache (opsiyonel future use)
            if live_role:
                bot.app_state.live_roles[guild.id] = live_role.id

        except Exception as e:
            logger.error(f"Startup error in guild {guild.id}: {e}")

    logger.info("✅ Startup sync completed")
