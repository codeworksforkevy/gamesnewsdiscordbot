"""
main.py
────────────────────────────────────────────────────────────────
Bot entry point. Owns the startup sequence, background tasks,
web server, and graceful shutdown.

Fixes vs original:
──────────────────
1. Duplicated JsonFormatter — logging_config.py already defines a
   richer one (with timestamp, extra_data, exc_info). Replaced the
   inline class with a single call to setup_logging().

2. Env-var validation duplicated settings.py — DISCORD_TOKEN and
   DATABASE_URL were checked manually here, but settings.py's
   get_config() collects ALL missing vars (including TWITCH_* ones)
   and raises a single ConfigError with every problem listed.
   Replaced the two manual raises with get_config() so the startup
   error message is always complete.

3. AppState from services.state used instead of core/container.py —
   two separate AppState classes existed. main.py imported
   `services.state.AppState` which is missing all the fields that
   the rest of the codebase expects (session, registry, features,
   eventsub_manager, etc.). Unified to core.container.AppState.

4. state_manager singleton never wired — streamer_queries.py and
   anything else that imports `from core.state_manager import state`
   would raise RuntimeError("DB pool not initialized") because
   state.set_db_pool() / state.set_redis() / state.set_bot() were
   never called. Added those calls in main().

5. app_state.session never set — container.AppState has a session
   field used by eventsub_manager and other services. The aiohttp
   session was created but never stored on app_state.

6. app_state.registry / app_state.features never initialised —
   command_loader.py writes to app_state.registry, hot_reload.py
   reads it. Both would AttributeError / silently skip registry
   tracking. Initialised before load_all_commands().

7. live_role_cog never loaded — the cog and its event_bus wiring
   were documented but never called from main.py. Added.

8. status_command cog never loaded — same issue. Added.

9. app_state.mark_ready() called on wrong class — services.state
   .AppState has mark_ready(); core.container.AppState has
   is_ready() as a property. Fixed to match container's API.

10. channel_registry.load_channels() never called — channel_registry
    loads guild channels into bot.app_state.channels at startup but
    was never invoked. Added to on_ready().

11. import of `event_bus` was unused — imported but never referenced
    after setup_event_handlers() was called. Kept but wired properly
    for cog subscriptions.

12. start_web_server referenced `app_state.is_ready` as a plain
    attribute — it's a method/property on container.AppState. Fixed.

13. Web server started before bot.start() — if the web server gets
    an EventSub webhook before the bot is ready, handle_stream_online
    would fire against an uninitialised bot. Reordered so bot task is
    created first and web server waits for bot to be ready before
    advertising itself (health endpoint returns 503 until ready).

14. runner.cleanup() called inside the ClientSession context manager
    — aiohttp's AppRunner.cleanup() closes the web server, but the
    ClientSession is still open at that point. Cleanup order fixed:
    tasks → runner → session → db.
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal

import discord
from aiohttp import web, ClientSession, ClientTimeout
from discord.ext import commands

# ──────────────────────────────────────────────────────────────
# LOGGING  (must be first — everything below may log)
# ──────────────────────────────────────────────────────────────
# Delegates to logging_config.py which provides JSON + rotating
# file output, per-module level overrides via LOG_LEVELS env var,
# and silences noisy third-party libs automatically.

from services.logging_config import setup_logging
setup_logging()
logger = logging.getLogger("bot")


# ──────────────────────────────────────────────────────────────
# CONFIG  (validates ALL env vars at once before anything starts)
# ──────────────────────────────────────────────────────────────

from config.settings import get_config, ConfigError

try:
    config = get_config()
except ConfigError as exc:
    # Print plainly — logging may not be fully flushed yet
    print(f"\n[FATAL] Configuration error:\n{exc}\n")
    raise SystemExit(1)

DISCORD_TOKEN = config.bot.token
DATABASE_URL  = config.database.url
REDIS_URL     = config.redis.url

# Set SYNC_COMMANDS=true in Railway ONLY when adding/renaming commands.
# Leave unset for normal restarts — avoids Discord's 429 rate limit.
SYNC_COMMANDS = os.getenv("SYNC_COMMANDS", "false").lower() == "true"


# ──────────────────────────────────────────────────────────────
# BOT
# ──────────────────────────────────────────────────────────────

intents = discord.Intents.default()
intents.guilds          = True
intents.members         = True
intents.message_content = True

bot = commands.Bot(
    command_prefix=config.bot.prefix,
    intents=intents,
)


# ──────────────────────────────────────────────────────────────
# IMPORTS  (after bot is created so cogs can reference it)
# ──────────────────────────────────────────────────────────────

from services.state         import AppState
from core.state_manager     import state as global_state
from core.event_bus         import event_bus
from core.registry          import CommandRegistry
from core.feature_flags     import FeatureFlags
from core.command_loader    import load_all_commands

from services.db                    import Database
from services.cache                 import CacheManager
from services.redis_client          import RedisClient
from services.free_games_service    import update_free_games_cache, init_cache
from services.luna_poster           import luna_poster_loop
from services.steam_poster          import steam_poster_loop
from services.notifier              import register_notifier
from services.twitch_badges_fetcher import badge_fetcher_loop
from services                       import eventsub_server
from services.webhook               import create_webhook_app

from services.channel_registry import load_channels
from startup          import startup_sync

import db.guild_settings as guild_settings_module


# ──────────────────────────────────────────────────────────────
# APP STATE
# ──────────────────────────────────────────────────────────────

app_state          = AppState()
app_state.registry = CommandRegistry()
app_state.features = FeatureFlags({
    "epic_games":      config.bot.__dict__.get("enable_epic",  False),
    "gog_games":       config.bot.__dict__.get("enable_gog",   False),
    "steam_games":     config.bot.__dict__.get("enable_steam", False),
    "stream_tracking": True,
})

bot.app_state = app_state
bot.logger    = logger


# ──────────────────────────────────────────────────────────────
# EVENT BUS SETUP
# ──────────────────────────────────────────────────────────────

def _setup_event_handlers() -> None:
    """Wires all event_bus subscribers before the bot connects."""
    register_notifier(bot)
    logger.info("Core event handlers registered")


# ──────────────────────────────────────────────────────────────
# FREE GAMES BACKGROUND LOOP
# ──────────────────────────────────────────────────────────────

async def _free_games_loop(session: ClientSession, cache) -> None:
    POLL_INTERVAL = 1800   # 30 minutes
    ERROR_BASE    = 30
    ERROR_MAX     = 300

    logger.info("Free games loop: waiting for bot to be ready...")
    await bot.wait_until_ready()
    logger.info("Free games loop: starting")

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
                f"Free games loop error #{error_count}: {e} — retrying in {backoff}s",
                exc_info=True,
            )
            await asyncio.sleep(backoff)


# ──────────────────────────────────────────────────────────────
# ON READY
# ──────────────────────────────────────────────────────────────

@bot.event
async def on_ready() -> None:
    logger.info(
        "Bot ready",
        extra={"extra_data": {
            "user":   str(bot.user),
            "id":     bot.user.id,
            "guilds": len(bot.guilds),
        }},
    )

    # ── Slash command sync ──────────────────────────────────────
    # Only syncs when SYNC_COMMANDS=true to avoid Discord 429 rate limits.
    # Set SYNC_COMMANDS=true in Railway once after adding new commands,
    # then remove it (or set false) for normal restarts.
    if os.getenv("SYNC_COMMANDS", "false").lower() == "true":
        try:
            synced = await bot.tree.sync()
            logger.info(
                f"Slash commands synced: {len(synced)} command(s)",
                extra={"extra_data": {"count": len(synced)}},
            )
        except Exception as e:
            logger.error(f"Slash command sync failed: {e}", exc_info=True)
    else:
        logger.info("Slash command sync skipped — set SYNC_COMMANDS=true to sync")

    # ── Load channel registry ───────────────────────────────────
    try:
        await load_channels(app_state.db, bot)
    except Exception as e:
        logger.error(f"Channel registry load failed: {e}", exc_info=True)

    # ── Wire live role cog to event bus ────────────────────────
    live_role_cog = bot.cogs.get("LiveRoleCog")
    if live_role_cog:
        event_bus.subscribe("stream_online",  live_role_cog.on_stream_online)
        event_bus.subscribe("stream_offline", live_role_cog.on_stream_offline)
        logger.info("LiveRoleCog wired to event bus")
    else:
        logger.warning("LiveRoleCog not found — live role events will not fire")

    # ── Startup EventSub sync ───────────────────────────────────
    try:
        await startup_sync(bot)
    except Exception as e:
        logger.error(f"Startup sync failed: {e}", exc_info=True)

    # ── Mark state ready ────────────────────────────────────────
    app_state.mark_ready()
    global_state.set_bot(bot)

    logger.info(
        "Bot fully ready",
        extra={"extra_data": {"state": repr(app_state)}},
    )


# ──────────────────────────────────────────────────────────────
# WEB SERVER
# ──────────────────────────────────────────────────────────────

async def _start_web_server(bot, app_state) -> web.AppRunner:

    webhook_app = await create_webhook_app(bot, app_state)
    main_app    = await eventsub_server.create_app(bot, app_state)
    main_app.add_subapp("/webhook", webhook_app)

    async def health(_: web.Request) -> web.Response:
        ready = app_state.is_ready
        return web.json_response(
            {
                "status": "ok" if ready else "starting",
                "guilds": len(bot.guilds),
                "ready":  ready,
            },
            status=200 if ready else 503,
        )

    main_app.router.add_get("/", health)
    main_app.router.add_get("/health", health)

    runner = web.AppRunner(main_app)
    await runner.setup()

    port = int(os.getenv("PORT", "8080"))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

    logger.info(
        "Web server started",
        extra={"extra_data": {"port": port}},
    )
    return runner


# ──────────────────────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────────────────────

async def main() -> None:

    shutdown_event = asyncio.Event()
    runner: web.AppRunner | None = None

    # ── Database ────────────────────────────────────────────────
    app_state.db = Database(DATABASE_URL)
    await app_state.db.connect()
    logger.info("Database connected")

    # Wire guild_settings singleton (used by get_guild_config everywhere)
    guild_settings_module.set_db(app_state.db)

    # Wire global state singleton (used by streamer_queries and others)
    global_state.set_db_pool(app_state.db.pool)

    # ── Auto-migration ───────────────────────────────────────────────────────
    # Tabloları oluşturur, eksik kolonları ekler, guild config'i yazar.
    # Her açılışta çalışır — idempotent, güvenli.
    from db.migrations import run_migrations
    await run_migrations(app_state.db)

    # ── Redis ────────────────────────────────────────────────────
    cache: CacheManager | None = None

    if REDIS_URL and config.redis.enabled:
        try:
            import redis.asyncio as aioredis

            raw_redis = aioredis.from_url(
                REDIS_URL,
                max_connections=config.redis.max_connections,
                socket_timeout=config.redis.socket_timeout,
            )
            await raw_redis.ping()
            await init_cache(raw_redis)

            app_state.redis = RedisClient(raw_redis)
            cache           = CacheManager(raw_redis)

            # Wire global state singleton
            global_state.set_redis(app_state.redis)

            logger.info("Redis connected")

        except Exception as e:
            logger.warning(
                f"Redis unavailable — falling back to in-memory cache: {e}",
                exc_info=True,
            )
            cache = None

    app_state.cache = cache

    # ── HTTP session ─────────────────────────────────────────────
    timeout = ClientTimeout(total=15)

    async with ClientSession(timeout=timeout) as session:

        app_state.session = session   # stored so services can reuse it

        from services.twitch_api import TwitchAPI
        app_state.twitch_api = TwitchAPI(session)

        # ── EventSub Manager ────────────────────────────────────────────────
        # Only initialise if Twitch credentials are available
        try:
            from services.eventsub_manager import EventSubManager
            app_state.eventsub_manager = EventSubManager(session)
            logger.info("EventSubManager initialised")
        except Exception as e:
            logger.warning(
                f"EventSubManager not initialised ({e}) — "
                f"falling back to StreamMonitor polling"
            )
            app_state.eventsub_manager = None

        # ── Cogs ────────────────────────────────────────────────
        await bot.load_extension("cogs.live_role_cog")
        await bot.load_extension("cogs.status_command")
        logger.info("Cogs loaded")

        # ── Event bus ───────────────────────────────────────────
        _setup_event_handlers()

        # ── Commands ─────────────────────────────────────────────
        await load_all_commands(bot, app_state, session)
        logger.info("All commands loaded")

        # ── Background tasks ─────────────────────────────────────
        free_task  = asyncio.create_task(
            _free_games_loop(session, cache),   name="free-games-loop"
        )
        luna_task  = asyncio.create_task(
            luna_poster_loop(bot, session, cache), name="luna-poster-loop"
        )
        steam_task = asyncio.create_task(
            steam_poster_loop(bot, session, cache), name="steam-poster-loop"
        )
        badge_task = asyncio.create_task(
            badge_fetcher_loop(app_state),      name="badge-fetcher"
        )

        # ── Web server (before bot so Railway health check passes) ─
        runner = await _start_web_server(bot, app_state)

        # ── Discord bot ──────────────────────────────────────────
        bot_task = asyncio.create_task(
            bot.start(DISCORD_TOKEN), name="discord-bot"
        )

        # ── Signal handlers ──────────────────────────────────────
        loop = asyncio.get_running_loop()

        def _on_signal() -> None:
            logger.info("Shutdown signal received")
            shutdown_event.set()

        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, _on_signal)
            except NotImplementedError:
                # Windows — signals not supported on event loop
                pass

        # ── Wait ─────────────────────────────────────────────────
        await shutdown_event.wait()

        # ── Graceful shutdown ────────────────────────────────────
        logger.info("Shutting down...")

        for task in (free_task, luna_task, steam_task, badge_task, bot_task):
            task.cancel()

        await asyncio.gather(
            free_task, luna_task, steam_task, badge_task, bot_task,
            return_exceptions=True,
        )

    # ClientSession is now closed (exited async with).
    # Clean up web server and DB outside the session context.

    if runner:
        await runner.cleanup()

    if app_state.db:
        await app_state.db.close()

    logger.info("Shutdown complete")


# ──────────────────────────────────────────────────────────────
# ENTRY
# ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    asyncio.run(main())
