"""
core/container.py
────────────────────────────────────────────────────────────────
Central application state container passed through the entire bot.

Fixes vs original:
- `os` was never imported → os.getenv("WEBHOOK_URL") crashed at startup
- No type hints made it hard to know what each field held
- Missing fields that are used across the codebase (session, channels,
  bot reference, live_notifier) added here so there's one source of truth

All fields are Optional and default to None/empty so the container can
be constructed early in startup before services are initialised.
"""

import os
from typing import Optional, Any

import aiohttp
import asyncpg


class AppState:

    def __init__(
        self,
        db: Optional[asyncpg.Pool] = None,
        redis: Optional[Any]       = None,
        config: Optional[dict]     = None,
    ):
        # ── Core services ───────────────────────────────────────
        self.db:     Optional[asyncpg.Pool] = db
        self.redis:  Optional[Any]          = redis
        self.config: dict                   = config or {}

        # ── HTTP session (shared aiohttp.ClientSession) ─────────
        self.session: Optional[aiohttp.ClientSession] = None

        # ── Bot reference ───────────────────────────────────────
        self.bot: Optional[Any] = None

        # ── Feature toggles & registry ──────────────────────────
        self.features: Optional[Any] = None   # FeatureFlags instance
        self.registry: Optional[Any] = None   # CommandRegistry instance

        # ── Twitch services ─────────────────────────────────────
        self.twitch_api:       Optional[Any] = None
        self.eventsub_manager: Optional[Any] = None
        self.cache:            Optional[Any] = None   # MetadataCache

        # ── Notification state ──────────────────────────────────
        # guild_id → Role  (populated by LiveRoleCog on startup)
        self.live_roles: dict[int, Any] = {}

        # Flat list loaded by channel_registry.load_channels()
        self.channels: list[dict] = []

        # ── Environment ─────────────────────────────────────────
        self.webhook_url: Optional[str] = os.getenv("WEBHOOK_URL")

    # ──────────────────────────────────────────────────────────
    # CONVENIENCE HELPERS
    # ──────────────────────────────────────────────────────────

    def is_ready(self) -> bool:
        """Returns True when the minimum required services are available."""
        return self.db is not None and self.bot is not None

    def __repr__(self) -> str:
        return (
            f"<AppState db={'✓' if self.db else '✗'} "
            f"redis={'✓' if self.redis else '✗'} "
            f"twitch_api={'✓' if self.twitch_api else '✗'}>"
        )
