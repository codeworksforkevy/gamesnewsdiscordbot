# config/settings.py

import os
from dataclasses import dataclass
from typing import Optional


# =================================================
# ENV HELPERS
# =================================================
def get_env(key: str, default: Optional[str] = None) -> Optional[str]:
    return os.getenv(key, default)


def get_env_int(key: str, default: int) -> int:
    try:
        return int(os.getenv(key, default))
    except (TypeError, ValueError):
        return default


def get_env_bool(key: str, default: bool = False) -> bool:
    val = os.getenv(key)

    if val is None:
        return default

    return val.lower() in ("1", "true", "yes", "on")


# =================================================
# CONFIG CLASSES
# =================================================
@dataclass
class DatabaseConfig:
    url: str
    min_pool: int = 1
    max_pool: int = 10
    timeout: int = 30


@dataclass
class RedisConfig:
    url: Optional[str] = None
    enabled: bool = False


@dataclass
class BotConfig:
    token: str
    prefix: str = "!"
    guild_debug_id: Optional[int] = None


@dataclass
class AppConfig:
    debug: bool
    environment: str

    database: DatabaseConfig
    redis: RedisConfig
    bot: BotConfig


# =================================================
# LOAD CONFIG
# =================================================
def load_config() -> AppConfig:

    # ENV
    environment = get_env("ENVIRONMENT", "production")
    debug = get_env_bool("DEBUG", False)

    # DATABASE
    database = DatabaseConfig(
        url=get_env("DATABASE_URL"),
        min_pool=get_env_int("DB_POOL_MIN", 1),
        max_pool=get_env_int("DB_POOL_MAX", 10),
        timeout=get_env_int("DB_TIMEOUT", 30),
    )

    if not database.url:
        raise RuntimeError("DATABASE_URL is not set")

    # REDIS
    redis = RedisConfig(
        url=get_env("REDIS_URL"),
        enabled=get_env_bool("REDIS_ENABLED", False),
    )

    # BOT
    bot = BotConfig(
        token=get_env("DISCORD_TOKEN"),
        prefix=get_env("BOT_PREFIX", "!"),
        guild_debug_id=get_env_int("GUILD_DEBUG_ID", None),
    )

    if not bot.token:
        raise RuntimeError("DISCORD_TOKEN is not set")

    return AppConfig(
        debug=debug,
        environment=environment,
        database=database,
        redis=redis,
        bot=bot,
    )


# =================================================
# GLOBAL CONFIG INSTANCE
# =================================================
config = load_config()
