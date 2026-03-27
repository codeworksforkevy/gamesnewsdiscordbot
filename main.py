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
DATABASE_URL  = os.getenv("DATABASE_URL")
REDIS_URL     = os.getenv("REDIS_URL")

# Set SYNC_COMMANDS=true in Railway env vars ONLY when you add/rename
# a command. Leave it unset (or false) for normal restarts to avoid
# the 429 rate limit on every deploy.
SYNC_COMMANDS = os.getenv("SYNC_COMMANDS", "false").lower() == "true"

if not DISCORD_TOKEN:
    raise RuntimeError("DISCORD_TOKEN is not set in environment variables")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is not set in environment variables")


# ==================================================
# LOGGING
# ==================================================

class JsonFormatter(logging.Formatter):
    def format(self, record):
        return json.dumps({
            "level":   record.levelname,
            "logger":  record.name,
            "message": record.getMessage(),
        })


_handler = logging.StreamHandler()
_handler.setFormatter(JsonFormatter())
root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)
root_logger.handlers.clear()
root_logger.addHandler(_handler)
logger = logging.getLogger("bot")


# ==================================================
# BOT
# ==================================================

intents = discord.Intents.default()
intents.guilds          = True
intents.members         = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)


# ==================================================
# IMPORTS
# ==================================================

from services.db    import Database
from services.state import AppState
from services.cache import CacheManager
from services.redis_client import RedisClient

from services.free_games_service     import update_free_games_cache, init_cache
from services.luna_poster            import luna_poster_loop
from services.steam_poster           import steam_poster_loop
from services.notifier               import register_notifier
from services.twitch_badges_fetcher  import badge_fetcher_loop

from startup import startup_sync

from core.command_loader import load_all_commands
from core.event_bus      import event_bus

from services.webhook import create_webhook_app
from services import eventsub_server

import db.guild_settings as guild_settings_module


# ==================================================
# APP STATE
# ==================================================

app_state     = AppState()
bot.app_state = app_state
bot.logger    = logger


# ==================================================
# EVENT BUS
# ==================================================

def setup_event_handlers() -> None:
    register_notifier(bot)
    logger.info("Event handlers registered")


# ==================================================
# FREE GAMES LOOP
# ==================================================

async def free_games_loop(session, cache) -> None:

    POLL_INTERVAL = 1800
    ERROR_BASE    = 30
    ERROR_MAX     = 300

    logger.info("Free games loop: waiting for bot to be ready...")
    await bot.wait_until_ready()
    logger.info("Free games loop: starting first fetch")

    error_count = 0

    while True:
        try:
            await update_free_games_cache(session, redis=cache)
            error_count = 0
            await asyncio.sleep(POLL_INTERVAL)
        except asyncio.CancelledError:
            logger.info("Free games loop cancelled")
            break
        except Exception as e:
            error_count += 1
            backoff = min(ERROR_BASE * (2 ** (error_count - 1)), ERROR_MAX)
            logger.error(
                f"Free games loop error #{error_count}: {e} — retrying in {backoff}s"
            )
            await asyncio.sleep(backoff)


# ==================================================
# ON READY
# FIX: slash command sync only runs when SYNC_COMMANDS=true
# to avoid hitting Discord's 429 rate limit on every deploy.
# Set SYNC_COMMANDS=true in Railway env vars when you add new commands,
# then remove it (or set to false) for normal restarts.
# ==================================================

@bot.event
async def on_ready():
    logger.info(f"Logged in as {bot.user} (ID: {bot.user.id})")
    logger.info(f"Connected to {len(bot.guilds)} guild(s)")

    if SYNC_COMMANDS:
        try:
            synced = await bot.tree.sync()
            logger.info(f"Slash commands synced: {len(synced)} command(s)")
        except Exception as e:
            logger.error(f"Slash command sync failed: {e}")
    else:
        logger.info("Slash command sync skipped (set SYNC_COMMANDS=true to sync)")

    try:
        await startup_sync(bot)
    except Exception as e:
        logger.error(f"Startup sync failed: {e}", exc_info=True)

    app_state.mark_ready()
    logger.info("Bot is fully ready")


# ==================================================
# WEB SERVER
# ==================================================

async def start_web_server(bot, app_state):

    webhook_app = await create_webhook_app(bot, app_state)
    main_app    = await eventsub_server.create_app(bot, app_state)
    main_app.add_subapp("/webhook", webhook_app)

    async def health(_):
        return web.json_response({
            "status": "ok",
            "guilds": len(bot.guilds),
            "ready":  app_state.is_ready,
        })

    main_app.router.add_get("/", health)

    runner = web.AppRunner(main_app)
    await runner.setup()

    port = int(os.getenv("PORT", "8080"))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

    logger.info(f"Web server started on port {port}")
    return runner


# ==================================================
# MAIN
# ==================================================

async def main():

    shutdown_event = asyncio.Event()

    # ── Database ───────────────────────────────────────────────────────────
    app_state.db = Database(DATABASE_URL)
    await app_state.db.connect()
    logger.info("Database connected")

    guild_settings_module.set_db(app_state.db)

    # ── Redis ──────────────────────────────────────────────────────────────
    cache = None

    if REDIS_URL:
        try:
            import redis.asyncio as aioredis
            raw_redis       = aioredis.from_url(REDIS_URL)
            app_state.redis = RedisClient(raw_redis)
            cache           = CacheManager(raw_redis)
            await raw_redis.ping()
            await init_cache(raw_redis)
            logger.info("Redis connected successfully")
        except Exception as e:
            logger.warning(f"Redis unavailable — falling back to memory cache: {e}")
            cache = None

    app_state.cache = cache

    # ── HTTP session ───────────────────────────────────────────────────────
    timeout = ClientTimeout(total=15)

    async with ClientSession(timeout=timeout) as session:

        from services.twitch_api import TwitchAPI
        app_state.twitch_api = TwitchAPI(session)

        setup_event_handlers()

        await load_all_commands(bot, app_state, session)
        logger.info("All commands loaded")

        free_task  = asyncio.create_task(
            free_games_loop(session, cache), name="free-games-loop"
        )
        luna_task  = asyncio.create_task(
            luna_poster_loop(bot, session, cache), name="luna-poster-loop"
        )
        steam_task = asyncio.create_task(
            steam_poster_loop(bot, session, cache), name="steam-poster-loop"
        )
        badge_task = asyncio.create_task(
            badge_fetcher_loop(app_state), name="badge-fetcher"
        )

        runner = await start_web_server(bot, app_state)

        bot_task = asyncio.create_task(
            bot.start(DISCORD_TOKEN), name="discord-bot"
        )

        loop = asyncio.get_running_loop()

        def _shutdown():
            logger.info("Shutdown signal received")
            shutdown_event.set()

        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, _shutdown)
            except NotImplementedError:
                pass

        await shutdown_event.wait()

        logger.info("Shutting down...")
        free_task.cancel()
        luna_task.cancel()
        steam_task.cancel()
        badge_task.cancel()
        bot_task.cancel()

        await asyncio.gather(
            free_task, luna_task, steam_task, badge_task, bot_task,
            return_exceptions=True,
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
