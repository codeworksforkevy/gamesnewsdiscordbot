from __future__ import annotations

import os
import asyncio
import logging
import signal

from aiohttp import web, ClientSession
import discord
from discord.ext import commands

# ==================================================
# ENV
# ==================================================

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")

if not DISCORD_TOKEN:
    raise RuntimeError("DISCORD_TOKEN missing")

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL missing")

# ==================================================
# LOGGING
# ==================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
)

logger = logging.getLogger("find-a-curie")

# ==================================================
# DISCORD SETUP
# ==================================================

intents = discord.Intents.default()
intents.message_content = False

bot = commands.Bot(command_prefix="!", intents=intents)

# ==================================================
# IMPORTS
# ==================================================

from services.db import Database
from services.state import AppState
from services.eventsub_server import create_eventsub_app
from services.free_games_service import update_free_games_cache
from services.monitor import TwitchMonitor
from services import twitch_api, eventsub_manager

from commands.live_commands import register_live_commands
from commands.discounts import register as register_discounts
from commands.free_games import register as register_free_games
from commands.membership import register as register_membership
from commands.twitch_badges import register as register_twitch_badges
from commands.utilities.register import register_utilities

# ==================================================
# APP STATE
# ==================================================

app_state = AppState()


# ==================================================
# READY EVENT
# ==================================================

@bot.event
async def on_ready():
    logger.info("Bot ready: %s", bot.user)

    try:
        synced = await bot.tree.sync()
        logger.info("Global sync complete (%s commands).", len(synced))
    except Exception:
        logger.exception("Slash sync failed")


# ==================================================
# WEB SERVER
# ==================================================

async def start_web_server(bot, app_state: AppState):

    async def health(request):
        return web.json_response({"status": "ok"})

    app = await create_eventsub_app(bot, app_state)
    app.router.add_get("/", health)

    runner = web.AppRunner(app)
    await runner.setup()

    port = int(os.getenv("PORT", "8080"))
    site = web.TCPSite(runner, host="0.0.0.0", port=port)
    await site.start()

    logger.info("Web server running on port %s", port)

    return runner


# ==================================================
# FREE GAME LOOP
# ==================================================

async def free_games_loop(session):
    while True:
        try:
            await update_free_games_cache(session)
        except Exception as e:
            logger.error("Free games update failed: %s", e)

        await asyncio.sleep(1800)


# ==================================================
# MAIN
# ==================================================

async def main():

    shutdown_event = asyncio.Event()

    # ------------------------------
    # DATABASE INIT
    # ------------------------------

    app_state.db = Database(DATABASE_URL)
    await app_state.db.connect()

    logger.info("Database ready.")

    pool = app_state.db.get_pool()

    # ------------------------------
    # HTTP SESSION
    # ------------------------------

    async with ClientSession() as session:

        # ------------------------------
        # REGISTER COMMANDS
        # ------------------------------

        register_live_commands(bot)
        await register_discounts(bot, session)
        await register_free_games(bot, session)
        await register_membership(bot, session)
        await register_twitch_badges(bot, session)
        await register_utilities(bot)

        # ------------------------------
        # BACKGROUND TASKS
        # ------------------------------

        free_task = asyncio.create_task(free_games_loop(session))

        monitor = TwitchMonitor(
            twitch_api=twitch_api,
            eventsub_manager=eventsub_manager,
            db_pool=pool,
            interval=300
        )

        monitor_task = asyncio.create_task(monitor.start())

        # ------------------------------
        # WEB SERVER
        # ------------------------------

        runner = await start_web_server(bot, app_state)

        # ------------------------------
        # SIGNAL HANDLING
        # ------------------------------

        loop = asyncio.get_running_loop()

        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, shutdown_event.set)

        bot_task = asyncio.create_task(bot.start(DISCORD_TOKEN))

        # Wait for shutdown
        await shutdown_event.wait()

        logger.info("Shutdown signal received.")

        # ------------------------------
        # CLEAN SHUTDOWN
        # ------------------------------

        free_task.cancel()
        monitor_task.cancel()
        bot_task.cancel()

        try:
            await runner.cleanup()
        except Exception:
            pass

        try:
            await app_state.db.close()
        except Exception:
            pass

        logger.info("Shutdown complete.")


if __name__ == "__main__":
    asyncio.run(main())
