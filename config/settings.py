"""
settings.py
────────────────────────────────────────────────────────────────
Central configuration loader. All environment variable access for
the entire bot flows through here.
"""

import logging
import os
from dataclasses import dataclass, field
from typing import Optional, List

logger = logging.getLogger("config")

class ConfigError(Exception):
    """Raised when required configuration is missing or invalid."""
    pass

@dataclass
class DatabaseConfig:
    url: str
    command_timeout: int = 30

@dataclass
class RedisConfig:
    url: str
    max_connections: int = 10
    socket_timeout: int = 5

@dataclass
class BotConfig:
    token: str
    prefix: str = "!"
    enable_epic: bool = False
    enable_gog: bool = False
    enable_steam: bool = False

@dataclass
class TwitchConfig:
    client_id: str
    client_secret: str
    eventsub_secret: str
    callback_url: str

@dataclass
class WebhookConfig:
    url: Optional[str]

@dataclass
class AppConfig:
    debug: bool
    environment: str
    database: DatabaseConfig
    redis: RedisConfig
    bot: BotConfig
    twitch: TwitchConfig
    webhook: WebhookConfig

def get_env(key: str, default: Optional[str] = None) -> str:
    val = os.getenv(key, default)
    if val is None:
        raise ConfigError(f"Missing required environment variable: {key}")
    return val

def get_env_bool(key: str, default: bool = False) -> bool:
    val = os.getenv(key, str(default)).lower()
    return val in ("true", "1", "yes")

def get_env_int(key: str, default: int) -> int:
    val = os.getenv(key, str(default))
    try:
        return int(val)
    except ValueError:
        raise ConfigError(f"Environment variable {key} must be an integer, got: {val}")

def load_config() -> AppConfig:
    errors: List[str] = []
    
    def collect_error(msg: str):
        errors.append(msg)

    # Helper to safely gather config without crashing early
    def safe_get(func, key, *args, **kwargs):
        try:
            return func(key, *args, **kwargs)
        except ConfigError as e:
            collect_error(str(e))
            return None

    # Load environment variables
    debug = get_env_bool("DEBUG", False)
    environment = os.getenv("ENVIRONMENT", "production")

    # Grouping configs
    db_url = safe_get(get_env, "DATABASE_URL")
    database = DatabaseConfig(url=db_url) if db_url else None

    redis_url = safe_get(get_env, "REDIS_URL")
    redis = RedisConfig(url=redis_url) if redis_url else None

    bot_token = safe_get(get_env, "DISCORD_TOKEN")
    bot = BotConfig(
        token=bot_token,
        prefix=os.getenv("COMMAND_PREFIX", "!"),
        enable_epic=get_env_bool("ENABLE_EPIC", False),
        enable_gog=get_env_bool("ENABLE_GOG", False),
        enable_steam=get_env_bool("ENABLE_STEAM", False)
    ) if bot_token else None

    twitch = TwitchConfig(
        client_id=safe_get(get_env, "TWITCH_CLIENT_ID"),
        client_secret=safe_get(get_env, "TWITCH_CLIENT_SECRET"),
        eventsub_secret=safe_get(get_env, "TWITCH_EVENTSUB_SECRET"),
        callback_url=os.getenv("TWITCH_CALLBACK_URL", "")
    )

    webhook = WebhookConfig(url=os.getenv("WEBHOOK_URL"))

    if errors:
        raise ConfigError("\n  - " + "\n  - ".join(errors))

    return AppConfig(
        debug=debug,
        environment=environment,
        database=database,  # type: ignore
        redis=redis,        # type: ignore
        bot=bot,            # type: ignore
        twitch=twitch,      # type: ignore
        webhook=webhook
    )

_config: Optional[AppConfig] = None

def get_config() -> AppConfig:
    global _config
    if _config is None:
        _config = load_config()
    return _config
