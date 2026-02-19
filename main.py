from __future__ import annotations

import os
import asyncio
import logging
from aiohttp import web
import aiohttp
import discord
from discord.ext import commands, tasks

# ==========================================================
# ENV
# ==========================================================

ENV = os.getenv("ENV", "production").lower()
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
BOT_OWNER_ID = int(os.getenv("BOT_OWNER_ID", "0"))
GUILD_ID = int(os.getenv("DEV_GUILD_ID", "0"))

if not DISCORD_TOKEN:
    raise RuntimeError("DISCORD_TOKEN missing")

# ==========================================================
# LOGGING
# ==========================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
)

logger = logging.getLogger("find-a-curie")

# ==========================================================
# DISCORD SETUP
# ==========================================================

# No privileged intents required (slash-only bot)
intents = discord.Intents.default()

bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

# ==========================================================
# GLOBAL ADMIN GUARD
# ==========================================================

@tree.interaction_check
async def admin_guard(interaction: discord.Interaction) -> bool:

    # Owner allowed
    if interaction.user.id == BOT_OWNER_ID:
        return True

    # Guild admin allowed
    if interaction.guild and interaction.user.guild_permissions.administrator:
        return True

    if not interaction.response.is_done():
        await interaction.response.send_message(
            "You must be an administrator to use this command.",
            ephemeral=True
        )

    return False

# ==========================================================
# IMPORT MODULES
# ==========================================================

from commands.free_games import register_free_games
from commands.twitch_badges import register_twitch_badges
from commands.live_commands import register_live_commands

from tasks.freegames_updater import update_free_games
from tasks.twitch_updater import update_twitch_badges

from services.http_client import http_client
from services.eventsub_server import create_eventsub_app
from services.subscription_manager import ensure_subscriptions

# ==========================================================
# CACHE LOOP
# ==========================================================

CACHE_UPDATE_INTERVAL = 3600  # 1 hour

@tasks.loop(seconds=CACHE_UPDATE_INTERVAL)
async def cache_loop():
    logger.info("Running scheduled cache update...")

    async with aiohttp.ClientSession() as session:
        await update_free_games(session)
        await update_twitch_badges(session)

    logger.info("Scheduled cache update complete.")

# ==========================================================
# READY EVENT
# ==========================================================

@bot.event
async def on_ready():

    logger.info("Bot ready: %s", bot.user)

    # Prevent duplicate on_ready executions
    if getattr(bot, "_ready_ran", False):
        return
    bot._ready_ran = True

    # Initial cache fill
    async with aiohttp.ClientSession() as session:
        await update_free_games(session)
        await update_twitch_badges(session)

    logger.info("Initial cache populated.")

    # Sync slash commands
    if ENV == "dev" and GUILD_ID:
        guild = discord.Object(id=GUILD_ID)
        tree.copy_global_to(guild=guild)
        await tree.sync(guild=guild)
        logger.info("Dev guild sync complete.")
    else:
        await tree.sync()
        logger.info("Global sync complete.")

    # Start background loop
    if not cache_loop.is_running():
        cache_loop.start()

    # Ensure Twitch EventSub subscriptions
    try:
        await ensure_subscriptions()
        logger.info("Subscription check complete.")
    except Exception as e:
        logger.exception("Subscription check failed: %s", e)

# ==========================================================
# EVENTSUB WEB SERVER
# ==========================================================

async def health(request: web.Request):
    return web.json_response({
        "status": "ok",
        "env": ENV
    })

async def start_web_server():

    app = create_eventsub_app(bot)
    app.router.add_get("/", health)

    runner = web.AppRunner(app)
    await runner.setup()

    port = int(os.getenv("PORT", "8080"))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

    logger.info("Web server running on port %s", port)

# ==========================================================
# MODULE REGISTRATION
# ==========================================================

async def setup_modules():
    await register_free_games(tree)
    await register_twitch_badges(tree)
    register_live_commands(bot)

# ==========================================================
# SHUTDOWN HANDLER
# ==========================================================

async def shutdown():
    logger.info("Shutting down...")
    await http_client.close()
    await bot.close()

# ==========================================================
# MAIN
# ==========================================================

async def main():

    await http_client.start()

    await setup_modules()

    await start_web_server()

    try:
        await bot.start(DISCORD_TOKEN)
    finally:
        await shutdown()

if __name__ == "__main__":
    asyncio.run(main())
