import discord
import logging

logger = logging.getLogger("startup")


# ==================================================
# LIVE ROLE SETUP
# ==================================================

async def ensure_live_role(guild: discord.Guild):

    role = discord.utils.get(guild.roles, name="Live")

    if role:
        return role

    logger.info("Creating Live role in %s", guild.name)

    return await guild.create_role(
        name="Live",
        color=discord.Color.from_rgb(137, 207, 240),  # Baby Blue
        mentionable=True
    )


# ==================================================
# STARTUP SYNC
# ==================================================

async def startup_sync(bot):

    db = bot.app_state.db
    eventsub = bot.app_state.eventsub_manager

    logger.info("Running startup sync...")

    # 🔹 Tüm guild'ler
    for guild in bot.guilds:

        # 1. Live role
        await ensure_live_role(guild)

        # 2. DB streamer'ları çek
        streamers = await db.fetch(
            "SELECT streamer_id FROM streamers WHERE guild_id=$1",
            guild.id
        )

        for s in streamers:

            broadcaster_id = s["streamer_id"]

            try:
                # 3. EventSub tekrar kur
                await eventsub.subscribe_all(broadcaster_id)

            except Exception as e:
                logger.error("Startup subscription failed: %s", e)

    logger.info("Startup sync completed.")
