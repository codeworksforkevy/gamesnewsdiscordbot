from __future__ import annotations

import os
import asyncio
import logging
import signal
import json

from aiohttp import web, ClientSession, ClientTimeout
import discord
from discord.ext import commands

# ==================================================
# ENV
# ==================================================

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
REDIS_URL = os.getenv("REDIS_URL")

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

from services.redis_client import RedisClient

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
# READY EVENT
# ==================================================

@bot.event
async def on_ready():
    logger.info(
        "Bot ready",
        extra={"extra_data": {"user": str(bot.user)}}
    )

    try:
        await startup_sync(bot)
    except Exception as e:
        logger.exception(
            "Startup failed",
            extra={"extra_data": {"error": str(e)}}
        )

    try:
        synced = await bot.tree.sync()
        logger.info(
            "Slash synced",
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

async def start_web_server(bot, app_state, monitor):

    async def health(_):
        return web.json_response({"status": "ok"})

    async def metrics(_):
        return web.Response(
            text="bot_up 1",
            content_type="text/plain"
        )

    app = await eventsub_server.create_app(bot, app_state)

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
# FREE GAMES LOOP (UPDATED)
# ==================================================

async def free_games_loop(session, bot, redis_client):

    while True:
        try:
            await update_free_games_cache(
                session,
                bot=bot,
                redis=redis_client
            )

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

    # -------------------------
    # DB
    # -------------------------
    app_state.db = Database(DATABASE_URL)
    await app_state.db.connect()

    logger.info("Database connected")

    # -------------------------
    # CACHE (Redis)
    # -------------------------
    await init_cache()

    redis_client = None

    if REDIS_URL:
        try:
            import redis.asyncio as redis

            redis_client = RedisClient(redis.from_url(REDIS_URL))

            logger.info("Redis client initialized")

        except Exception as e:
            logger.warning(
                "Redis init failed",
                extra={"extra_data": {"error": str(e)}}
            )

    # -------------------------
    # HTTP SESSION
    # -------------------------
    timeout = ClientTimeout(total=15)

    async with ClientSession(timeout=timeout) as session:

        # -------------------------
        # SERVICES
        # -------------------------
        from services import twitch_api
        from services.eventsub_manager import EventSubManager
        from services.twitch_monitor import TwitchMonitor

        app_state.twitch_api = twitch_api.TwitchAPI(session)
        app_state.eventsub_manager = EventSubManager(session)

        # -------------------------
        # COMMANDS
        # -------------------------
        register_live_commands(bot)

        await register_discounts(bot, session)
        await register_free_games(bot, session)
        await register_membership(bot, session)
        await register_twitch_badges(bot, session)
        await register_utilities(bot)
        await register_help(bot)

        # -------------------------
        # BACKGROUND TASKS
        # -------------------------
        free_task = asyncio.create_task(
            free_games_loop(session, bot, redis_client)
        )

        monitor = TwitchMonitor(
            bot=bot,
            session=session,
            redis=redis_client,
            interval=180
        )

        monitor.start()

        runner = await start_web_server(bot, app_state, monitor)

        # -------------------------
        # SIGNAL HANDLING
        # -------------------------
        loop = asyncio.get_running_loop()

        try:
            for sig in (signal.SIGINT, signal.SIGTERM):
                loop.add_signal_handler(sig, shutdown_event.set)
        except NotImplementedError:
            logger.warning("Signal handlers not supported")

        bot_task = asyncio.create_task(bot.start(DISCORD_TOKEN))

        # -------------------------
        # WAIT
        # -------------------------
        await shutdown_event.wait()

        logger.info("Shutdown signal received")

        # -------------------------
        # CLEANUP
        # -------------------------
        monitor.stop()

        free_task.cancel()
        bot_task.cancel()

        await asyncio.gather(
            free_task,
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
