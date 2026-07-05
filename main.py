from __future__ import annotations

import asyncio
import logging
import os
import signal
import discord
from aiohttp import web, ClientSession, ClientTimeout
from discord.ext import commands

# LOGGING
from services.logging_config import setup_logging
setup_logging()
logger = logging.getLogger("bot")

# CONFIG
from config.settings import get_config, ConfigError
try:
    config = get_config()
except ConfigError as exc:
    print(f"\n[FATAL] Configuration error:\n{exc}\n")
    raise SystemExit(1)

DISCORD_TOKEN = config.bot.token
DATABASE_URL  = config.database.url
REDIS_URL     = config.redis.url
SYNC_COMMANDS = os.getenv("SYNC_COMMANDS", "false").lower() == "true"

# BOT SETUP
intents = discord.Intents.default()
intents.guilds = True
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix=config.bot.prefix, intents=intents)

# IMPORTS
from services.state import AppState
from core.state_manager import state as global_state
from core.event_bus import event_bus
from core.registry import CommandRegistry
from core.feature_flags import FeatureFlags
from core.command_loader import load_all_commands
from services.db import Database
from services.cache import CacheManager
from services.redis_client import RedisClient
from services.free_games_service import update_free_games_cache, init_cache
from services.luna_poster import luna_poster_loop
from services.steam_poster import steam_poster_loop
from services.notifier import register_notifier
from services.twitch_badges_fetcher import badge_fetcher_loop
from services import eventsub_server
from services.webhook import create_webhook_app
from services.channel_registry import load_channels
from startup import startup_sync
import db.guild_settings as guild_settings_module

# APP STATE
app_state = AppState()
app_state.registry = CommandRegistry()
app_state.features = FeatureFlags({
    "epic_games": config.bot.__dict__.get("enable_epic", False),
    "gog_games": config.bot.__dict__.get("enable_gog", False),
    "steam_games": config.bot.__dict__.get("enable_steam", False),
    "stream_tracking": True,
})
bot.app_state = app_state
bot.logger = logger

def _setup_event_handlers() -> None:
    register_notifier(bot)

    async def _on_streamer_added(payload: dict) -> None:
        eventsub = getattr(app_state, "eventsub_manager", None)
        if not eventsub: return
        twitch_user_id = payload.get("twitch_user_id")
        if not twitch_user_id: return
        callback_url = eventsub.callback_url
        if not callback_url: return
        try:
            await eventsub.ensure_subscriptions(str(twitch_user_id), callback_url)
        except Exception as e:
            logger.error(f"EventSub subscription error: {e}", exc_info=True)

    event_bus.subscribe("streamer_added", _on_streamer_added)

async def _free_games_loop(session: ClientSession, cache) -> None:
    await bot.wait_until_ready()
    while True:
        try:
            await update_free_games_cache(session, redis=cache)
            await asyncio.sleep(1800)
        except asyncio.CancelledError: break
        except Exception as e:
            logger.error(f"Free games loop error: {e}")
            await asyncio.sleep(300)

@bot.event
async def on_ready() -> None:
    bot.start_time = discord.utils.utcnow()
    logger.info(f"Bot ready: {bot.user}")
    
    if SYNC_COMMANDS:
        await bot.tree.sync()
    
    await load_channels(app_state.db, bot)
    
    live_role_cog = bot.cogs.get("LiveRoleCog")
    if live_role_cog:
        event_bus.subscribe("stream_online", live_role_cog.on_stream_online)
        event_bus.subscribe("stream_offline", live_role_cog.on_stream_offline)

    await startup_sync(bot)
    app_state.mark_ready()
    global_state.set_bot(bot)

async def _start_web_server(bot, app_state) -> web.AppRunner:
    webhook_app = await create_webhook_app(bot, app_state)
    main_app = await eventsub_server.create_app(bot, app_state)
    main_app.add_subapp("/webhook", webhook_app)
    runner = web.AppRunner(main_app)
    await runner.setup()
    port = int(os.getenv("PORT", "8080"))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    return runner

async def main() -> None:
    shutdown_event = asyncio.Event()
    
    app_state.db = Database(DATABASE_URL)
    await app_state.db.connect()
    guild_settings_module.set_db(app_state.db)
    global_state.set_db_pool(app_state.db.pool)

    from db.migrations import run_migrations
    await run_migrations(app_state.db)

    # Redis
    cache = None
    if REDIS_URL and config.redis.enabled:
        import redis.asyncio as aioredis
        raw_redis = aioredis.from_url(REDIS_URL)
        await init_cache(raw_redis)
        app_state.redis = RedisClient(raw_redis)
        cache = CacheManager(raw_redis)
        global_state.set_redis(app_state.redis)
    app_state.cache = cache

    async with ClientSession(timeout=ClientTimeout(total=15)) as session:
        app_state.session = session
        from services.twitch_api import TwitchAPI
        app_state.twitch_api = TwitchAPI(session)

        # EventSub Manager
        from services.eventsub_manager import EventSubManager
        app_state.eventsub_manager = EventSubManager(session)

        # Twitch Monitor Initialisation
        try:
            from monitor import TwitchMonitor
            from services import notifier
            
            app_state.monitor = TwitchMonitor(
                twitch_api=app_state.twitch_api,
                eventsub_manager=app_state.eventsub_manager,
                db_pool=app_state.db.pool,
                redis=app_state.redis,
                bot=bot,
                notifier=notifier
            )
            await app_state.monitor.start()
            logger.info("TwitchMonitor initialized.")
        except Exception as e:
            logger.error(f"Monitor init failed: {e}", exc_info=True)

        await bot.load_extension("cogs.live_role_cog")
        await bot.load_extension("cogs.status_command")
        # Load the new commands cog
        await bot.load_extension("commands.live_commands")
        
        _setup_event_handlers()
        await load_all_commands(bot, app_state, session)

        free_task = asyncio.create_task(_free_games_loop(session, cache))
        luna_task = asyncio.create_task(luna_poster_loop(bot, session, cache))
        steam_task = asyncio.create_task(steam_poster_loop(bot, session, cache))
        badge_task = asyncio.create_task(badge_fetcher_loop(app_state))
        
        runner = await _start_web_server(bot, app_state)
        bot_task = asyncio.create_task(bot.start(DISCORD_TOKEN))

        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, shutdown_event.set)

        await shutdown_event.wait()
        
        if hasattr(app_state, "monitor"):
            await app_state.monitor.stop()

        for task in (free_task, luna_task, steam_task, badge_task, bot_task):
            task.cancel()
        await runner.cleanup()
        await app_state.db.close()

if __name__ == "__main__":
    asyncio.run(main())

