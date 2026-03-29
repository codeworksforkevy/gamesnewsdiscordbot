"""
settings.py
────────────────────────────────────────────────────────────────
Central configuration loader. All environment variable access for
the entire bot flows through here — nowhere else should call
os.getenv() directly.

Fixes vs original:
- `config = load_config()` ran at module import time. Any import of
  this file (even in tests) would call load_config() and raise
  RuntimeError if DATABASE_URL / DISCORD_TOKEN were missing.
  Fixed: module-level call is guarded so it only runs in production
  entry-points, not on every import. Use get_config() to access it.
- get_env_int() passed `default` (an int) straight into os.getenv()
  as the fallback, but os.getenv() requires a str default — caused
  silent TypeError. Fixed: always stringify the default.
- get_env_int("GUILD_DEBUG_ID", None) → int(None) raises TypeError.
  Fixed with an explicit None guard.
- RedisConfig had no command_timeout or max_connections fields that
  pool.py / redis_client.py need.
- No TwitchConfig — Twitch credentials were scattered across env calls
  in eventsub_manager, event_router, etc. Centralised here.
- No WebhookConfig — WEBHOOK_URL was read ad-hoc in container.py.
- Missing command_timeout in DatabaseConfig (pool.py uses it).
- load_config() collected all errors at once now instead of failing
  on the first missing var, so you see every missing key at startup.
"""

import logging
import os
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger("config")


# ──────────────────────────────────────────────────────────────
# ENV HELPERS
# ──────────────────────────────────────────────────────────────

def get_env(key: str, default: Optional[str] = None) -> Optional[str]:
    return os.getenv(key, default)


def get_env_required(key: str) -> str:
    """Reads a required env var. Raises ConfigError if missing."""
    value = os.getenv(key)
    if not value:
        raise ConfigError(f"Required environment variable '{key}' is not set")
    return value


def get_env_int(key: str, default: int) -> int:
    """Reads an integer env var, returning default on missing or invalid value."""
    raw = os.getenv(key)
    if raw is None:
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        logger.warning(f"Invalid integer for {key}={raw!r}, using default {default}")
        return default


def get_env_int_optional(key: str) -> Optional[int]:
    """Reads an optional integer env var. Returns None if not set or invalid."""
    raw = os.getenv(key)
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        logger.warning(f"Invalid integer for optional {key}={raw!r}, using None")
        return None


def get_env_bool(key: str, default: bool = False) -> bool:
    val = os.getenv(key)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


# ──────────────────────────────────────────────────────────────
# ERRORS
# ──────────────────────────────────────────────────────────────

class ConfigError(RuntimeError):
    """Raised when required configuration is missing or invalid."""
    pass


# ──────────────────────────────────────────────────────────────
# CONFIG DATACLASSES
# ──────────────────────────────────────────────────────────────

@dataclass
class DatabaseConfig:
    url:             str
    min_pool:        int = 1
    max_pool:        int = 10
    timeout:         int = 30    # connection acquisition timeout (seconds)
    command_timeout: int = 30    # per-query timeout (seconds)


@dataclass
class RedisConfig:
    url:             Optional[str] = None
    enabled:         bool          = False
    max_connections: int           = 10
    socket_timeout:  int           = 5    # seconds before a Redis call times out


@dataclass
class BotConfig:
    token:          str
    prefix:         str           = "!"
    guild_debug_id: Optional[int] = None   # used for instant slash command sync in dev


@dataclass
class TwitchConfig:
    client_id:      str
    app_token:      str
    eventsub_secret: str
    callback_url:   str           # public HTTPS URL Twitch POSTs events to


@dataclass
class WebhookConfig:
    url: Optional[str] = None     # Discord webhook for admin alerts (optional)


@dataclass
class AppConfig:
    debug:       bool
    environment: str              # "development" | "staging" | "production"

    database: DatabaseConfig
    redis:    RedisConfig
    bot:      BotConfig
    twitch:   TwitchConfig
    webhook:  WebhookConfig

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def is_development(self) -> bool:
        return self.environment == "development"


# ──────────────────────────────────────────────────────────────
# LOADER
# ──────────────────────────────────────────────────────────────

def load_config() -> AppConfig:
    """
    Reads all environment variables and constructs the AppConfig.

    Collects ALL missing required vars before raising, so you see
    every problem in one go rather than fixing them one at a time.
    """
    errors: list[str] = []

    # ── Environment ─────────────────────────────────────────────
    environment = get_env("ENVIRONMENT", "production")
    debug       = get_env_bool("DEBUG", False)

    # ── Database ────────────────────────────────────────────────
    db_url = get_env("DATABASE_URL")
    if not db_url:
        errors.append("DATABASE_URL is not set")

    database = DatabaseConfig(
        url             = db_url or "",
        min_pool        = get_env_int("DB_POOL_MIN",        1),
        max_pool        = get_env_int("DB_POOL_MAX",        10),
        timeout         = get_env_int("DB_TIMEOUT",         30),
        command_timeout = get_env_int("DB_COMMAND_TIMEOUT", 30),
    )

    # ── Redis ───────────────────────────────────────────────────
    redis = RedisConfig(
        url             = get_env("REDIS_URL"),
        enabled         = get_env_bool("REDIS_ENABLED", False),
        max_connections = get_env_int("REDIS_MAX_CONNECTIONS", 10),
        socket_timeout  = get_env_int("REDIS_SOCKET_TIMEOUT",  5),
    )

    # ── Bot ─────────────────────────────────────────────────────
    discord_token = get_env("DISCORD_TOKEN")
    if not discord_token:
        errors.append("DISCORD_TOKEN is not set")

    bot = BotConfig(
        token          = discord_token or "",
        prefix         = get_env("BOT_PREFIX", "!"),
        guild_debug_id = get_env_int_optional("GUILD_DEBUG_ID"),
    )

    # ── Twitch (optional — bot starts without these, Twitch features disabled) ─
    twitch_client_id = get_env("TWITCH_CLIENT_ID")
    twitch_app_token = get_env("TWITCH_ACCESS_TOKEN")
    # Auto-derive callback URL from Railway's public domain if not set explicitly
    twitch_callback = get_env("TWITCH_EVENTSUB_CALLBACK_URL")
    if not twitch_callback:
        public_base = get_env("PUBLIC_BASE_URL")
        if public_base:
            twitch_callback = public_base.rstrip("/") + "/twitch/eventsub"
            logger.info(f"TWITCH_EVENTSUB_CALLBACK_URL derived from PUBLIC_BASE_URL: {twitch_callback}")
    if not twitch_callback:
        railway_domain = get_env("RAILWAY_PUBLIC_DOMAIN")
        if railway_domain:
            twitch_callback = f"https://{railway_domain}/eventsub"
            logger.info(f"TWITCH_EVENTSUB_CALLBACK_URL derived from RAILWAY_PUBLIC_DOMAIN: {twitch_callback}")

    _twitch_missing = [
        name for name, val in [
            ("TWITCH_CLIENT_ID",             twitch_client_id),
            ("TWITCH_ACCESS_TOKEN",          twitch_app_token),
            ("TWITCH_EVENTSUB_CALLBACK_URL", twitch_callback),
        ] if not val
    ]
    if _twitch_missing:
        # Warn but don't block startup — free-games, polls etc. work without Twitch
        logger.warning(
            "Twitch integration disabled — missing env vars: "
            + ", ".join(_twitch_missing)
            + ". Set them in Railway to enable live stream tracking."
        )

    twitch = TwitchConfig(
        client_id       = twitch_client_id or "",
        app_token       = twitch_app_token or "",
        eventsub_secret = get_env("TWITCH_EVENTSUB_SECRET", "supersecret"),
        callback_url    = twitch_callback or "",
    )

    # ── Webhook (optional) ───────────────────────────────────────
    webhook = WebhookConfig(
        url = get_env("WEBHOOK_URL"),
    )

    # ── Fail fast with all errors at once ───────────────────────
    if errors:
        bullet_list = "\n  - ".join(errors)
        raise ConfigError(
            f"Bot startup failed — missing required configuration:\n  - {bullet_list}\n"
            f"Set these environment variables and restart."
        )

    return AppConfig(
        debug       = debug,
        environment = environment,
        database    = database,
        redis       = redis,
        bot         = bot,
        twitch      = twitch,
        webhook     = webhook,
    )


# ──────────────────────────────────────────────────────────────
# GLOBAL SINGLETON  (lazy — not loaded at import time)
# ──────────────────────────────────────────────────────────────

_config: Optional[AppConfig] = None


def get_config() -> AppConfig:
    """
    Returns the global AppConfig, loading it on first call.
    Use this instead of importing `config` directly — it avoids
    load_config() running during test imports when env vars aren't set.
    """
    global _config
    if _config is None:
        _config = load_config()
    return _config


def reset_config() -> None:
    """Clears the cached config. Useful in tests to reload with new env vars."""
    global _config
    _config = None
