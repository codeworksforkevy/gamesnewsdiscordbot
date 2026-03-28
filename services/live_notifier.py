"""
services/live_notifier.py
────────────────────────────────────────────────────────────────
Lightweight polling-based stream state tracker.

This is the SIMPLE monitor — it polls Twitch every `interval` seconds
and emits event_bus events when a streamer goes live or offline.
It is a safety net alongside EventSub: if a webhook is missed, this
catches the transition on the next poll cycle.

Fixes vs original:
- Was only detecting went-live, never went-offline → fixed
- `stop()` was sync but `start()` was async-incompatible → both unified
- `event_bus.emit` used, but original called `event_bus.publish` in some
  places — normalised to `publish` to match event_bus.py
- Added structured logging with extra_data throughout
"""

import asyncio
import logging
from datetime import datetime, timezone

logger = logging.getLogger("live-notifier")


class LiveNotifier:

    def __init__(self, bot, app_state, interval: int = 60):
        self.bot        = bot
        self.app_state  = app_state
        self.interval   = interval

        self._running = False
        self._task: asyncio.Task | None = None

    # ──────────────────────────────────────────────────────────
    # LIFECYCLE
    # ──────────────────────────────────────────────────────────

    def start(self) -> None:
        if self._running:
            logger.warning("LiveNotifier already running — ignoring start()")
            return

        self._running = True
        self._task    = asyncio.create_task(self._loop())
        logger.info("LiveNotifier started", extra={"extra_data": {"interval": self.interval}})

    def stop(self) -> None:
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            logger.info("LiveNotifier stopped")

    # ──────────────────────────────────────────────────────────
    # MAIN LOOP
    # ──────────────────────────────────────────────────────────

    async def _loop(self) -> None:
        while self._running:
            try:
                await self._check_streams()
            except Exception as e:
                logger.error(
                    "Poll cycle error",
                    extra={"extra_data": {"error": str(e)}},
                    exc_info=True,
                )
            await asyncio.sleep(self.interval)

    # ──────────────────────────────────────────────────────────
    # CORE POLL
    # ──────────────────────────────────────────────────────────

    async def _check_streams(self) -> None:
        db         = self.app_state.db
        twitch_api = self.app_state.twitch_api

        rows = await db.fetch(
            "SELECT twitch_user_id, twitch_login FROM streamers"
        )

        for row in rows:
            user_id = row["twitch_user_id"]
            login   = row["twitch_login"]

            try:
                stream = await twitch_api.get_stream(user_id)

                # Load previous state from DB
                prev = await db.fetchrow(
                    "SELECT is_live FROM streamer_states WHERE twitch_user_id = $1",
                    user_id,
                )

                was_live = prev["is_live"] if prev else False
                is_live  = bool(stream)

                # ── Transition: offline → live ──────────────────
                if not was_live and is_live:
                    logger.info(
                        "Streamer went live",
                        extra={"extra_data": {"login": login, "user_id": user_id}},
                    )
                    await self._emit_online(user_id, login, stream)

                # ── Transition: live → offline ──────────────────
                elif was_live and not is_live:
                    logger.info(
                        "Streamer went offline",
                        extra={"extra_data": {"login": login, "user_id": user_id}},
                    )
                    await self._emit_offline(user_id, login)

                # ── Persist new state ───────────────────────────
                await db.execute(
                    """
                    INSERT INTO streamer_states (
                        twitch_user_id,
                        is_live,
                        title,
                        game_name,
                        viewer_count,
                        last_updated
                    )
                    VALUES ($1, $2, $3, $4, $5, $6)
                    ON CONFLICT (twitch_user_id) DO UPDATE SET
                        is_live      = EXCLUDED.is_live,
                        title        = EXCLUDED.title,
                        game_name    = EXCLUDED.game_name,
                        viewer_count = EXCLUDED.viewer_count,
                        last_updated = EXCLUDED.last_updated
                    """,
                    user_id,
                    is_live,
                    stream.get("title")        if stream else None,
                    stream.get("game_name")    if stream else None,
                    stream.get("viewer_count") if stream else None,
                    datetime.now(timezone.utc),
                )

            except Exception as e:
                logger.warning(
                    "Streamer check failed",
                    extra={"extra_data": {"login": login, "error": str(e)}},
                )

    # ──────────────────────────────────────────────────────────
    # EVENT EMITTERS
    # ──────────────────────────────────────────────────────────

    async def _emit_online(self, user_id: str, login: str, stream: dict) -> None:
        from core.event_bus import event_bus

        await event_bus.publish("stream_online", {
            "twitch_user_id":    user_id,
            "twitch_login":      login,
            "broadcaster_user_login": login,
            "broadcaster_user_name":  login,
            "stream":            stream,
        })

    async def _emit_offline(self, user_id: str, login: str) -> None:
        from core.event_bus import event_bus

        await event_bus.publish("stream_offline", {
            "twitch_user_id":         user_id,
            "twitch_login":           login,
            "broadcaster_user_login": login,
            "broadcaster_user_name":  login,
        })
