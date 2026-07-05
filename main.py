

```python
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
from core.state_manager      import state as global_state
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

    # Auto-subscribe to Twitch EventSub when a new streamer is added via /live add
    async def _on_streamer_added(payload: dict) -> None:
        eventsub = getattr(app_state, "eventsub_manager", None)
        if not eventsub:
            logger.warning("streamer_added: no EventSubManager — subscription skipped")
            return

        twitch_user_id = payload.get("twitch_user_id")
        twitch_login   = payload.get("twitch_login", "?")

        if not twitch_user_id:
            logger.warning(f"streamer_added: twitch_user_id missing ({twitch_login})")
            return

        callback_url = eventsub.callback_url
        if not callback_url:
            logger.warning(
                f"streamer_added: callback URL not configured — "
                f"subscription skipped for {twitch_login}"
            )
            return

        try:
            await eventsub.ensure_subscriptions(str(twitch_user_id), callback_url)
            logger.info(f"EventSub subscriptions created: {twitch_login}")
        except Exception as e:
            logger.error(f"EventSub subscription error for {twitch_login}: {e}", exc_info=True)

    event_bus.subscribe("streamer_added", _on_streamer_added)
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
async def on_command_error(ctx, error):
    """Suppress CommandNotFound — happens when someone types !anything."""
    if isinstance(error, commands.CommandNotFound):
        return  # silently ignore
    # Re-raise everything else
    raise error


@bot.event
async def on_ready() -> None:
    bot.start_time = discord.utils.utcnow()  # for /curie_status uptime
    logger.info(
        "Bot ready",
        extra={"extra_data": {
            "user":   str(bot.user),
            "id":     bot.user.id,
            "guilds": len(bot.guilds),
        }},
    )

    # ── Slash command sync ──────────────────────────────────────
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
    from db.migrations import run_migrations
    await run_migrations(app_state.db)

    # ── Guarantee stream_history exists ──────────────────────────────────────
    try:
        async with app_state.db.pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS stream_history (
                    id            BIGSERIAL   PRIMARY KEY,
                    twitch_login  TEXT        NOT NULL,
                    guild_id      BIGINT      NOT NULL,
                    title         TEXT,
                    game_name     TEXT,
                    peak_viewers  INTEGER     DEFAULT 0,
                    started_at    TIMESTAMPTZ,
                    ended_at      TIMESTAMPTZ,
                    duration_secs INTEGER     DEFAULT 0
                );
            """)
        logger.info("stream_history table verified")
    except Exception as e:
        logger.warning(f"stream_history table check failed: {e}")

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

        # ── Twitch Monitor (Watchdog Watcher Loop) ──────────────────────────
        try:
            from monitor import TwitchMonitor
            from services import notifier  # Imports the framework's core notifier module
            
            app_state.monitor = TwitchMonitor(
                twitch_api=app_state.twitch_api,
                eventsub_manager=app_state.eventsub_manager,
                db_pool=app_state.db.pool,
                redis=app_state.redis,
                bot=bot,
                notifier=notifier
            )
            await app_state.monitor.start()
            logger.info("TwitchMonitor self-healing watchdog cycle initialized successfully.")
        except Exception as e:
            logger.error(f"Failed to load or start TwitchMonitor engine layer: {e}", exc_info=True)

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
                # Windows fallback
                pass

        # ── Wait ─────────────────────────────────────────────────
        await shutdown_event.wait()

        # ── Graceful shutdown ────────────────────────────────────
        logger.info("Shutting down...")

        # Asynchronously stop the monitor loop and release locks
        if hasattr(app_state, "monitor") and app_state.monitor:
            try:
                await app_state.monitor.stop()
                logger.info("TwitchMonitor watchdog cycle stopped cleanly.")
            except Exception as e:
                logger.error(f"Error occurred during TwitchMonitor engine teardown: {e}")

        for task in (free_task, luna_task, steam_task, badge_task, bot_task):
            task.cancel()

        await asyncio.gather(
            free_task, luna_task, steam_task, badge_task, bot_task,
            return_exceptions=True,
        )

    # ClientSession is now closed.
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

```
