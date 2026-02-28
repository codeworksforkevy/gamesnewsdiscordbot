from __future__ import annotations

import os
import asyncio
import logging
import signal
import json

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
# STRUCTURED JSON LOGGING
# ==================================================

class JsonFormatter(logging.Formatter):
    def format(self, record):
        log_record = {
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        if hasattr(record, "extra_data"):
            log_record.update(record.extra_data)

        return json.dumps(log_record)


handler = logging.StreamHandler()
handler.setFormatter(JsonFormatter())

root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)
root_logger.handlers.clear()
root_logger.addHandler(handler)

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
from services.monitor import TwitchMonitor
from services.twitch_api import TwitchAPI
from services.eventsub_manager import EventSubManager
from services.free_games_service import (
    update_free_games_cache,
    init_cache
)

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
bot.app_state = app_state
bot.logger = logger


# ==================================================
# READY EVENT
# ==================================================

@bot.event
async def on_ready():
    logger.info(
        "Bot ready",
        extra={"extra_data": {"user": str(bot.user)}}
    )

    try:
        synced = await bot.tree.sync()
        logger.info(
            "Slash sync complete",
            extra={"extra_data": {"count": len(synced)}}
        )
    except Exception as e:
        logger.exception(
            "Slash sync failed",
            extra={"extra_data": {"error": str(e)}}
        )


# ==================================================
# WEB SERVER
# ==================================================

async def start_web_server(bot, app_state: AppState, monitor: TwitchMonitor):

    async def health(request):
        return web.json_response({"status": "ok"})

    async def metrics(request):
        m = monitor.get_metrics()

        payload = f"""
monitor_cycles_total {m['monitor_cycles_total']}
monitor_cycle_failures {m['monitor_cycle_failures']}
"""
        return web.Response(
            text=payload.strip(),
            content_type="text/plain"
        )

    app = await create_eventsub_app(bot, app_state)

    app.router.add_get("/", health)
    app.router.add_get("/metrics", metrics)

    runner = web.AppRunner(app)
    await runner.setup()

    port = int(os.getenv("PORT", "8080"))
    site = web.TCPSite(runner, host="0.0.0.0", port=port)
    await site.start()

    logger.info(
        "Web server started",
        extra={"extra_data": {"port": port}}
    )

    return runner


# ==================================================
# FREE GAME SCHEDULER
# ==================================================

async def free_games_loop(session):

    while True:
        try:
            await update_free_games_cache(session)

        except Exception as e:
            logger.error(
                "Free games update failed",
                extra={"extra_data": {"error": str(e)}}
            )

        await asyncio.sleep(1800)


# ==================================================
# MAIN
# ==================================================

async def main():

    shutdown_event = asyncio.Event()

    # -------------------------------------------------
    # DATABASE
    # -------------------------------------------------

    app_state.db = Database(DATABASE_URL)
    await app_state.db.connect()
    logger.info("Database connected")

    pool = app_state.db.get_pool()

    # -------------------------------------------------
    # CACHE INIT (Redis optional)
    # -------------------------------------------------

    await init_cache()

    # -------------------------------------------------
    # HTTP SESSION
    # -------------------------------------------------

    async with ClientSession() as session:

        # Core services
        app_state.twitch_api = TwitchAPI(session)
        app_state.eventsub_manager = EventSubManager(session)

        # Register commands
        register_live_commands(bot)
        await register_discounts(bot, session)
        await register_free_games(bot, session)
        await register_membership(bot, session)
        await register_twitch_badges(bot, session)
        await register_utilities(bot)

        # Background tasks
        free_task = asyncio.create_task(
            free_games_loop(session)
        )

        monitor = TwitchMonitor(
            twitch_api=app_state.twitch_api,
            eventsub_manager=app_state.eventsub_manager,
            db_pool=pool,
            interval=180
        )

        monitor_task = asyncio.create_task(
            monitor.start()
        )

        # Web server
        runner = await start_web_server(
            bot,
            app_state,
            monitor
        )

        # Signal handling
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, shutdown_event.set)

        bot_task = asyncio.create_task(
            bot.start(DISCORD_TOKEN)
        )

        # Wait
        await shutdown_event.wait()
        logger.info("Shutdown signal received")

        # Cleanup
        for task in (free_task, monitor_task, bot_task):
            task.cancel()

        await asyncio.gather(
            free_task,
            monitor_task,
            bot_task,
            return_exceptions=True
        )

        try:
            await runner.cleanup()
        except Exception:
            pass

        try:
            await app_state.db.close()
        except Exception:
            pass

        logger.info("Shutdown complete")


# ==================================================
# ENTRY
# ==================================================

if __name__ == "__main__":
    asyncio.run(main())
