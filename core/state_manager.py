"""
core/state_manager.py
────────────────────────────────────────────────────────────────
Global application state singleton used by DB query helpers and
services that can't easily receive app_state via dependency injection.

The full-featured AppState container lives in core/container.py.
This module provides the global `state` singleton and typed accessors
with helpful error messages when accessed before initialisation.

Improvements over original:
- Added get_redis() accessor with the same guard pattern as get_db_pool()
- Added set_bot() / get_bot() so cogs can reach the bot instance via state
- Added is_ready() for startup health checks
- Docstring explains relationship with container.py to avoid confusion
"""

from typing import Optional, Any
import asyncpg


class AppState:
    """
    Minimal global state singleton.

    For the full application container (passed explicitly through the
    bot startup chain) see core/container.py → AppState.
    This class exists so database query helpers (db/streamer_queries.py,
    etc.) can access the pool without import cycles.
    """

    def __init__(self):
        self._db_pool: Optional[asyncpg.Pool] = None
        self._redis:   Optional[Any]           = None
        self._bot:     Optional[Any]           = None

    # ──────────────────────────────────────────────────────────
    # DB POOL
    # ──────────────────────────────────────────────────────────

    def set_db_pool(self, pool: asyncpg.Pool) -> None:
        self._db_pool = pool

    def get_db_pool(self) -> asyncpg.Pool:
        if not self._db_pool:
            raise RuntimeError(
                "DB pool not initialised — call state.set_db_pool() "
                "from main.py before using any DB queries."
            )
        return self._db_pool

    # ──────────────────────────────────────────────────────────
    # REDIS
    # ──────────────────────────────────────────────────────────

    def set_redis(self, redis: Any) -> None:
        self._redis = redis

    def get_redis(self) -> Any:
        if not self._redis:
            raise RuntimeError(
                "Redis not initialised — call state.set_redis() "
                "from main.py before using any Redis operations."
            )
        return self._redis

    # ──────────────────────────────────────────────────────────
    # BOT
    # ──────────────────────────────────────────────────────────

    def set_bot(self, bot: Any) -> None:
        self._bot = bot

    def get_bot(self) -> Any:
        if not self._bot:
            raise RuntimeError(
                "Bot not set — call state.set_bot() after the bot is created."
            )
        return self._bot

    # ──────────────────────────────────────────────────────────
    # HEALTH
    # ──────────────────────────────────────────────────────────

    def is_ready(self) -> bool:
        """True when both DB pool and bot are available."""
        return self._db_pool is not None and self._bot is not None

    def __repr__(self) -> str:
        return (
            f"<AppState "
            f"db={'✓' if self._db_pool else '✗'} "
            f"redis={'✓' if self._redis else '✗'} "
            f"bot={'✓' if self._bot else '✗'}>"
        )


# ──────────────────────────────────────────────────────────────
# GLOBAL SINGLETON
# ──────────────────────────────────────────────────────────────

state = AppState()
