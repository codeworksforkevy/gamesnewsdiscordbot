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
# LOGGING
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

logger = logging.getLogger("bot")


# ==================================================
# DISCORD
# ==================================================

intents = discord.Intents.default()
intents.message_content = False
intents.guilds = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)


# ==================================================
# IMPORTS
# ==================================================

from services.db import Database
from services.state import AppState

from services.free_games_service import (
    update_free_games_cache,
    init_cache
)

from startup import startup_sync

from commands.live_commands import register_live_commands
from commands.discounts import register as register_discounts
from commands.free_games import register as register_free_games
from commands.membership import register as register_membership
from commands.twitch_badges import register as register_twitch_badges
from commands.utilities.register import register_utilities
from commands.help import register as register_help

from services import eventsub_server


# ==================================================
# APP STATE
# ==================================================

app_state = AppState()
bot.app_state = app_state
bot.logger = logger


# ==================================================
# READY
# ==================================================

@bot.event
async def on_ready():
    logger.info("Bot ready", extra={"extra_data": {"user": str(bot.user)}})

    try:
        await startup_sync(bot)
    except Exception as e:
        logger.exception(f"Startup failed: {e}")

    try:
        synced = await bot.tree.sync()
        logger.info("Slash synced", extra={"extra_data": {"count": len(synced)}})
    except Exception as e:
        logger.exception(f"Slash sync failed: {e}")


# ==================================================
# WEB SERVER
# ==================================================

async def start_web_server(bot, app_state, monitor):

    async def health(_):
        return web.json_response({"status": "ok"})

    async def metrics(_):
        m = monitor.get_metrics()

        return web.Response(
            text=f"""
monitor_cycles_total {m['monitor_cycles_total']}
monitor_cycle_failures {m['monitor_cycle_failures']}
""".strip(),
            content_type="text/plain"
        )

    app = await eventsub_server.create_app(bot, app_state)

    # ✅ FIX (aiohttp pattern)
    app["bot"] = bot
    app["app_state"] = app_state

    app.router.add_get("/", health)
    app.router.add_get("/metrics", metrics)

    runner = web.AppRunner(app)
    await runner.setup()

    port = int(os.getenv("PORT", "8080"))
    site = web.TCPSite(runner, "0.0.0.0", port)

    await site.start()

    logger.info(
        "Web server started",
        extra={"extra_data": {"port": port}}
    )

    return runner


# ==================================================
# LOOP
# ==================================================

async def free_games_loop(session):
    while True:
        try:
            await update_free_games_cache(session)
        except Exception as e:
            logger.error(
                "Free games failed",
                extra={"extra_data": {"error": str(e)}}
            )

        await asyncio.sleep(1800)


# ==================================================
# MAIN
# ==================================================

async def main():

    shutdown_event = asyncio.Event()

    # DB
    app_state.db = Database(DATABASE_URL)
    await app_state.db.connect()
    logger.info("Database connected")

    # CACHE
    await init_cache()

    async with ClientSession() as session:

        # Twitch API
        from services.twitch_api import init_twitch_api
        app_state.twitch_api = await init_twitch_api()

        # EventSub Manager
        from services.eventsub_manager import EventSubManager

        app_state.eventsub_manager = EventSubManager(session)

        # attach bot (legacy support)
        eventsub_server.bot_instance = bot

        # ==================================================
        # COMMANDS
        # ==================================================

        register_live_commands(bot)
        await register_discounts(bot, session)
        await register_free_games(bot, session)
        await register_membership(bot, session)
        await register_twitch_badges(bot, session)
        await register_utilities(bot)
        await register_help(bot)

        # ==================================================
        # TASKS
        # ==================================================

        free_task = asyncio.create_task(free_games_loop(session))

        from services.monitor import TwitchMonitor

        monitor = TwitchMonitor(
            twitch_api=app_state.twitch_api,
            eventsub_manager=app_state.eventsub_manager,
            db_pool=app_state.db.get_pool(),
            interval=180
        )

        monitor_task = asyncio.create_task(monitor.start())

        runner = await start_web_server(bot, app_state, monitor)

        # ==================================================
        # SIGNALS (Docker-safe)
        # ==================================================

        loop = asyncio.get_running_loop()

        try:
            for sig in (signal.SIGINT, signal.SIGTERM):
                loop.add_signal_handler(sig, shutdown_event.set)
        except NotImplementedError:
            # Windows / some environments
            logger.warning("Signal handlers not supported")

        bot_task = asyncio.create_task(bot.start(DISCORD_TOKEN))

        await shutdown_event.wait()

        logger.info("Shutdown signal received")

        # ==================================================
        # CLEANUP
        # ==================================================

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
