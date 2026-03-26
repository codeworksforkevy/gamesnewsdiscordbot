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
# LOGGING (RAILWAY SAFE)
# ==================================================

class JsonFormatter(logging.Formatter):
    def format(self, record):
        return json.dumps({
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        })


handler = logging.StreamHandler()
handler.setFormatter(JsonFormatter())

root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)
root_logger.handlers.clear()
root_logger.addHandler(handler)

logger = logging.getLogger("bot")


# ==================================================
# BOT
# ==================================================

intents = discord.Intents.default()
intents.guilds = True
intents.members = True
intents.message_content = True  # FIXED

bot = commands.Bot(command_prefix="!", intents=intents)


# ==================================================
# IMPORTS (CORE ONLY)
# ==================================================

from services.db import Database
from services.state import AppState
from services.cache import CacheManager
from services.redis_client import RedisClient

from services.free_games_service import (
    update_free_games_cache,
    init_cache
)

from startup import startup_sync

# ✅ NEW SYSTEM
from core.command_loader import load_all_commands
from core.event_bus import event_bus

from services.webhook import create_webhook_app
from services import eventsub_server


# ==================================================
# APP STATE
# ==================================================

app_state = AppState()
bot.app_state = app_state
bot.logger = logger


# ==================================================
# EVENT BUS HOOKS
# ==================================================

async def setup_event_handlers():
    """
    Event-driven notifier binding
    """

    from services.notifier import notify_discord

    async def handle_free_games(games):
        await notify_discord(bot, games, redis=app_state.cache)

    event_bus.subscribe("free_games_fetched", handle_free_games)


# ==================================================
# Replace your existing free_games_loop in main.py
# with this version.
# ==================================================
 
async def free_games_loop(session, cache, app_state):
    """
    Polls Epic + GOG every 30 minutes for new free games.
 
    Fixes applied vs original:
    1. Waits for the bot to be fully ready (DB pool initialized,
       Discord gateway connected) before the first fetch.
       This prevents the "DB pool not initialized" race condition.
    2. Uses exponential backoff on errors (30s → 60s → 120s)
       instead of always waiting the full 30 minutes on failure.
    3. Passes app_state so the notifier can reach the DB pool.
    """
 
    POLL_INTERVAL = 1800   # 30 minutes between successful fetches
    ERROR_BASE    = 30     # seconds to wait after first failure
    ERROR_MAX     = 300    # cap backoff at 5 minutes
 
    # ── Wait for bot + DB to be fully ready ────────────────────────────────
    logger.info("Free games loop: waiting for bot to be ready...")
    while not app_state.is_ready():
        await asyncio.sleep(2)
    logger.info("Free games loop: bot is ready — starting first fetch")
 
    error_count = 0
 
    while True:
        try:
            await update_free_games_cache(
                session,
                redis=cache,
            )
            error_count = 0                      # reset backoff on success
            await asyncio.sleep(POLL_INTERVAL)
 
        except asyncio.CancelledError:
            logger.info("Free games loop cancelled — shutting down cleanly")
            break
 
        except Exception as e:
            error_count += 1
            backoff = min(ERROR_BASE * (2 ** (error_count - 1)), ERROR_MAX)
            logger.error(
                f"Free games loop error (attempt {error_count}): {e} "
                f"— retrying in {backoff}s"
            )
            await asyncio.sleep(backoff)
 
 
# ==================================================
# Also update this line in main() where you create
# the background task — add app_state argument:
#
# OLD:
#   free_task = asyncio.create_task(
#       free_games_loop(session, cache)
#   )
#
# NEW:
#   free_task = asyncio.create_task(
#       free_games_loop(session, cache, app_state)
#   )
# ==================================================


# ==================================================
# WEB SERVER
# ==================================================

async def start_web_server(bot, app_state):

    webhook_app = await create_webhook_app(bot, app_state)
    main_app = await eventsub_server.create_app(bot, app_state)

    main_app.add_subapp("/webhook", webhook_app)

    async def health(_):
        return web.json_response({"status": "ok"})

    main_app.router.add_get("/", health)

    runner = web.AppRunner(main_app)
    await runner.setup()

    port = int(os.getenv("PORT", "8080"))
    site = web.TCPSite(runner, "0.0.0.0", port)

    await site.start()

    logger.info(f"Web server started on {port}")

    return runner


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
    # REDIS + CACHE
    # -------------------------
    cache = None

    if REDIS_URL:
        try:
            import redis.asyncio as redis

            raw = redis.from_url(REDIS_URL)

            app_state.redis = RedisClient(raw)
            cache = CacheManager(raw)

            await init_cache(raw)

            logger.info("Redis enabled")

        except Exception as e:
            logger.warning(f"Redis fallback: {e}")

    app_state.cache = cache

    # -------------------------
    # HTTP SESSION
    # -------------------------
    timeout = ClientTimeout(total=15)

    async with ClientSession(timeout=timeout) as session:

        # -------------------------
        # SERVICES
        # -------------------------
        from services import twitch_api
        app_state.twitch_api = twitch_api.TwitchAPI(session)

        # -------------------------
        # EVENT BUS
        # -------------------------
        await setup_event_handlers()

        # -------------------------
        # AUTO COMMAND LOADER ✅
        # -------------------------
        await load_all_commands(bot, app_state, session)

        logger.info("All commands loaded")

        # -------------------------
        # STARTUP SYNC
        # -------------------------
        try:
            await startup_sync(bot)
        except Exception as e:
            logger.error(f"Startup sync failed: {e}")

        # -------------------------
        # BACKGROUND TASKS
        # -------------------------
        free_task = asyncio.create_task(
            free_games_loop(session, cache)
        )

        # -------------------------
        # WEB SERVER
        # -------------------------
        runner = await start_web_server(bot, app_state)

        # -------------------------
        # BOT START
        # -------------------------
        bot_task = asyncio.create_task(bot.start(DISCORD_TOKEN))

        # -------------------------
        # SIGNAL HANDLING
        # -------------------------
        loop = asyncio.get_running_loop()

        def _shutdown():
            shutdown_event.set()

        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, _shutdown)
            except NotImplementedError:
                pass

        await shutdown_event.wait()

        logger.info("Shutdown signal received")

        # -------------------------
        # CLEANUP
        # -------------------------
        free_task.cancel()
        bot_task.cancel()

        await asyncio.gather(
            free_task,
            bot_task,
            return_exceptions=True
        )

        await runner.cleanup()

        if app_state.db:
            await app_state.db.close()

        logger.info("Shutdown complete")


# ==================================================
# ENTRY
# ==================================================

if __name__ == "__main__":
    asyncio.run(main())
