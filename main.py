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
intents.message_content = True  # 🔥 EKLE

bot = commands.Bot(command_prefix="!", intents=intents)


# ==================================================
# IMPORTS
# ==================================================

from services.db import Database
from services.state import AppState
from services.cache import CacheManager
from services.fetch_router import FetchRouter

from services.free_games_service import update_free_games_cache, init_cache

from services.redis_client import RedisClient

from startup import startup_sync

from commands.live_commands import register_live_commands
from commands.discounts import register as register_discounts
from commands.free_games import register as register_free_games
from commands.membership import register as register_membership
from commands.twitch_badges import register as register_twitch_badges
from commands.utilities.register import register_utilities
from commands.help import register as register_help

from services.webhook import create_webhook_app
from services import eventsub_server


# ==================================================
# APP STATE
# ==================================================

app_state = AppState()
bot.app_state = app_state
bot.logger = logger


# ==================================================
# FREE GAME LOOP (WITH DEDUP)
# ==================================================

async def free_games_loop(session, bot, cache):

    while True:
        try:
            key = "free_games"

            if await cache.is_duplicate(key):
                logger.info("Duplicate fetch skipped")
            else:
                await update_free_games_cache(session, bot=bot, redis=cache)

        except Exception as e:
            logger.error(str(e))

        await asyncio.sleep(1800)


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

    return runner


# ==================================================
# MAIN
# ==================================================

async def main():

    shutdown_event = asyncio.Event()

    # DB
    app_state.db = Database(DATABASE_URL)
    await app_state.db.connect()

    # REDIS
    cache = None
    redis_client = None

    if REDIS_URL:
        try:
            import redis.asyncio as redis
            raw = redis.from_url(REDIS_URL)

            redis_client = RedisClient(raw)
            cache = CacheManager(raw)

            await init_cache(raw)

            logger.info("Redis enabled")

        except Exception as e:
            logger.warning(f"Redis fallback: {e}")

    # HTTP
    timeout = ClientTimeout(total=15)

    async with ClientSession(timeout=timeout) as session:

        app_state.cache = cache

        # SERVICES
        from services import twitch_api
        app_state.twitch_api = twitch_api.TwitchAPI(session)

        # COMMANDS
        register_live_commands(bot)
        await register_discounts(bot, session)
        await register_free_games(bot, session)
        await register_membership(bot, session)
        await register_twitch_badges(bot, session)
        await register_utilities(bot)
        await register_help(bot)

        # LOOP
        free_task = asyncio.create_task(
            free_games_loop(session, bot, cache)
        )

        # WEB
        runner = await start_web_server(bot, app_state)

        bot_task = asyncio.create_task(bot.start(DISCORD_TOKEN))

        # SIGNAL
        loop = asyncio.get_running_loop()

        def _shutdown():
            shutdown_event.set()

        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, _shutdown)
            except NotImplementedError:
                pass

        await shutdown_event.wait()

        free_task.cancel()
        bot_task.cancel()

        await asyncio.gather(free_task, bot_task, return_exceptions=True)

        await runner.cleanup()
        await app_state.db.close()

        logger.info("Shutdown complete")


# ENTRY

if __name__ == "__main__":
    asyncio.run(main())
