from __future__ import annotations

import asyncio
from typing import Optional, Any


class AppState:
    """
    Central application state container.

    Pattern:
    - Dependency Injection container
    - Shared resources across modules
    - Async-safe structures
    """

    def __init__(self):
        # =========================
        # CORE SERVICES
        # =========================
        self.db: Optional[Any] = None
        self.cache: Optional[Any] = None

        # =========================
        # REDIS / CACHE CLIENT
        # =========================
        self.redis = None

        # =========================
        # API CLIENTS
        # =========================
        self.twitch_api = None
        self.eventsub_manager = None

        # =========================
        # DISCORD BOT REFERENCE
        # =========================
        self.bot = None

        # =========================
        # EVENT SYSTEM (ASYNC)
        # =========================
        self.event_bus = None

        # =========================
        # TRIGGER / MESSAGE QUEUE
        # (Webhook, background triggers vs.)
        # =========================
        self.trigger_queue: asyncio.Queue = asyncio.Queue()

        # =========================
        # INTERNAL FLAGS
        # =========================
        self.is_ready: bool = False
        self.is_shutting_down: bool = False

        # =========================
        # METRICS / OBSERVABILITY
        # =========================
        self.metrics: dict[str, Any] = {
            "free_games_fetch_count": 0,
            "cache_hits": 0,
            "cache_misses": 0,
            "errors": 0,
        }

        # =========================
        # CONFIG CACHE (runtime)
        # =========================
        self.config_cache: dict[str, Any] = {}

        # =========================
        # SOURCE PRIORITY (FAILOVER)
        # =========================
        self.source_priority: list[str] = [
            "primary",
            "secondary",
            "tertiary",
        ]

    # ==================================================
    # STATE HELPERS
    # ==================================================

    def set_bot(self, bot):
        self.bot = bot

    def mark_ready(self):
        self.is_ready = True

    def mark_shutdown(self):
        self.is_shutting_down = True

    # ==================================================
    # CONFIG HELPERS
    # ==================================================

    def get_config(self, key: str, default=None):
        return self.config_cache.get(key, default)

    def set_config(self, key: str, value: Any):
        self.config_cache[key] = value

    # ==================================================
    # METRICS
    # ==================================================

    def inc_metric(self, key: str, value: int = 1):
        if key not in self.metrics:
            self.metrics[key] = 0
        self.metrics[key] += value

    def get_metrics(self) -> dict:
        return self.metrics

    # ==================================================
    # CACHE TRACKING
    # ==================================================

    def cache_hit(self):
        self.inc_metric("cache_hits")

    def cache_miss(self):
        self.inc_metric("cache_misses")

    # ==================================================
    # EVENT BUS HOOK
    # ==================================================

    async def emit(self, event_name: str, payload: dict):
        """
        If event bus exists, emit event.
        Otherwise fallback to queue.
        """
        if self.event_bus:
            await self.event_bus.publish(event_name, payload)
        else:
            await self.trigger_queue.put({
                "event": event_name,
                "payload": payload
            })

    async def next_event(self):
        """
        Consume next trigger event from queue.
        """
        return await self.trigger_queue.get()

    # ==================================================
    # SAFE ACCESSORS
    # ==================================================

    def require_db(self):
        if not self.db:
            raise RuntimeError("Database not initialized")
        return self.db

    def require_cache(self):
        if not self.cache:
            raise RuntimeError("Cache not initialized")
        return self.cache

    def require_bot(self):
        if not self.bot:
            raise RuntimeError("Bot not initialized")
        return self.bot

    # ==================================================
    # SOURCE HANDLING
    # ==================================================

    def get_next_source(self, failed_sources: set[str]) -> Optional[str]:
        """
        Returns next available source not yet failed.
        """
        for source in self.source_priority:
            if source not in failed_sources:
                return source
        return None
