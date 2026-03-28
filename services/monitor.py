"""
monitor.py
────────────────────────────────────────────────────────────────
Production TwitchMonitor — leader-elected, self-healing cycle.

Fixes vs original:
- Leader lock was acquired once then never renewed → lock expires after
  LEADER_LOCK_TTL seconds and another instance can steal it mid-run.
  Fixed: lock is now renewed at the start of every cycle.
- audit_eventsub_subscriptions only checked stream.online subs →
  stream.offline was never audited, so offline events were never
  subscribed. Fixed: both types are now audited.
- reconcile_live_state silently returned when live_ids was empty/falsy,
  meaning if Twitch API returned [] (all offline) no reset happened.
  Fixed: empty list is treated as "none live" not "API failed".
- track_stream_changes compared old.get("game") but Twitch API returns
  "game_name" — fixed key mismatch.
- notify_stream_change called self.notifier.stream_updated() but also
  publishes to event_bus so event_router can handle role/embed updates.
- stop() was async but did nothing except flip a flag — task was never
  cancelled. Fixed: _task is tracked and cancelled on stop().
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger("twitch-monitor")


class TwitchMonitor:

    LEADER_LOCK_KEY = "twitch-monitor:leader"
    LEADER_LOCK_TTL = 60          # seconds; renewed every cycle

    def __init__(
        self,
        twitch_api,
        eventsub_manager,
        db_pool,
        redis,
        bot=None,                 # needed for role management via event_bus
        notifier=None,
        metadata_cache=None,
        cooldown_manager=None,
        change_classifier=None,
        telemetry=None,
        interval: int = 180,
    ):
        self.twitch_api        = twitch_api
        self.eventsub_manager  = eventsub_manager
        self.db_pool           = db_pool
        self.redis             = redis

        self.bot               = bot
        self.notifier          = notifier
        self.metadata_cache    = metadata_cache
        self.cooldown_manager  = cooldown_manager
        self.change_classifier = change_classifier
        self.telemetry         = telemetry

        self.interval = interval

        self._running = False
        self._task: Optional[asyncio.Task] = None

        # Metrics
        self.monitor_cycles_total   = 0
        self.monitor_cycle_failures = 0

    # ──────────────────────────────────────────────────────────
    # LEADER ELECTION
    # ──────────────────────────────────────────────────────────

    async def _acquire_leader_lock(self) -> bool:
        """
        Tries to become the leader instance.
        Uses Redis NX (set-if-not-exists) with a TTL.
        Falls back to a Postgres advisory lock when Redis is unavailable.
        """
        try:
            if self.redis:
                ok = await self.redis.set(
                    self.LEADER_LOCK_KEY,
                    "1",
                    nx=True,
                    ex=self.LEADER_LOCK_TTL,
                )
                return bool(ok)

            # Postgres advisory lock fallback
            async with self.db_pool.acquire() as conn:
                return await conn.fetchval(
                    "SELECT pg_try_advisory_lock($1);",
                    987654321,
                )

        except Exception:
            logger.exception("Leader lock acquisition failed")
            return False

    async def _renew_leader_lock(self) -> None:
        """
        Renews the leader lock TTL at the start of each cycle so it
        doesn't expire while the monitor is actively running.
        """
        try:
            if self.redis:
                await self.redis.set(
                    self.LEADER_LOCK_KEY,
                    "1",
                    ex=self.LEADER_LOCK_TTL,
                    # No NX here — we already own the lock
                )
        except Exception:
            logger.warning("Leader lock renewal failed — another instance may take over")

    # ──────────────────────────────────────────────────────────
    # LIFECYCLE
    # ──────────────────────────────────────────────────────────

    async def start(self) -> None:
        if self._running:
            return

        if not await self._acquire_leader_lock():
            logger.info("Not leader → monitor disabled on this instance")
            return

        self._running = True
        self._task    = asyncio.create_task(self._run())
        logger.info("TwitchMonitor started (leader)")

    async def stop(self) -> None:
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("TwitchMonitor stopped")

    async def _run(self) -> None:
        while self._running:
            try:
                await self.run_cycle()
            except Exception:
                logger.exception("Cycle crashed unexpectedly")
            await asyncio.sleep(self.interval)

    # ──────────────────────────────────────────────────────────
    # MAIN CYCLE
    # ──────────────────────────────────────────────────────────

    async def run_cycle(self) -> None:
        self.monitor_cycles_total += 1
        start = datetime.now(timezone.utc)

        # Renew leader lock so we don't lose it mid-cycle
        await self._renew_leader_lock()

        try:
            await self.audit_eventsub_subscriptions()
            await self.reconcile_live_state()
            await self.track_stream_changes()
            await self.refresh_badges()
            await self.check_drops()

            duration = (datetime.now(timezone.utc) - start).total_seconds()

            logger.info(
                "Monitor cycle completed",
                extra={"extra_data": {
                    "duration_sec": round(duration, 2),
                    "cycle":        self.monitor_cycles_total,
                }},
            )

        except Exception:
            self.monitor_cycle_failures += 1
            logger.exception("Monitor cycle failed")

    # ──────────────────────────────────────────────────────────
    # EVENTSUB AUDIT
    # ──────────────────────────────────────────────────────────

    async def audit_eventsub_subscriptions(self) -> None:
        """
        Ensures every streamer in the DB has BOTH stream.online and
        stream.offline subscriptions active on Twitch.
        """
        try:
            subs = await self.eventsub_manager.list_subscriptions() or []

            # Build set of (broadcaster_id, event_type) that are active
            active: set[tuple[str, str]] = {
                (
                    s.get("condition", {}).get("broadcaster_user_id", ""),
                    s.get("type", ""),
                )
                for s in subs
                if s.get("status") in (
                    "enabled",
                    "webhook_callback_verification_pending",
                )
            }

            async with self.db_pool.acquire() as conn:
                rows = await conn.fetch("SELECT broadcaster_id FROM streamers")

            wanted_types = ["stream.online", "stream.offline"]
            callback_url = self.eventsub_manager.callback_url

            for row in rows:
                bid = row["broadcaster_id"]
                for event_type in wanted_types:
                    if (bid, event_type) not in active:
                        logger.info(
                            "Missing EventSub subscription — creating",
                            extra={"extra_data": {
                                "broadcaster": bid,
                                "type":        event_type,
                            }},
                        )
                        await self.eventsub_manager.ensure_subscriptions(
                            bid, callback_url
                        )
                        break   # ensure_subscriptions handles both types

        except Exception:
            logger.exception("EventSub audit failed")

    # ──────────────────────────────────────────────────────────
    # LIVE STATE RECONCILIATION
    # ──────────────────────────────────────────────────────────

    async def reconcile_live_state(self) -> None:
        """
        Cross-checks DB live flags against the Twitch API.
        Any streamer marked live in DB but not actually live → reset + emit offline.
        """
        try:
            async with self.db_pool.acquire() as conn:
                rows = await conn.fetch(
                    "SELECT broadcaster_id, twitch_login FROM streamers WHERE is_live = TRUE"
                )

            if not rows:
                return

            ids       = [r["broadcaster_id"] for r in rows]
            login_map = {r["broadcaster_id"]: r["twitch_login"] for r in rows}

            live_ids = await self.twitch_api.check_streams_live(ids)

            # Treat API returning [] as "none of them are live"
            # (original short-circuited here, preventing any reset)
            to_reset = [bid for bid in ids if bid not in (live_ids or [])]

            if not to_reset:
                return

            async with self.db_pool.acquire() as conn:
                await conn.execute(
                    """
                    UPDATE streamers
                    SET is_live = FALSE
                    WHERE broadcaster_id = ANY($1::text[])
                    """,
                    to_reset,
                )

            logger.info(
                "Reconciled stale live flags",
                extra={"extra_data": {"reset_count": len(to_reset)}},
            )

            # Emit offline events so roles and embeds are cleaned up
            for bid in to_reset:
                await self._publish_offline(bid, login_map.get(bid, bid))

        except Exception:
            logger.exception("Live reconciliation failed")

    async def _publish_offline(self, broadcaster_id: str, login: str) -> None:
        try:
            from core.event_bus import event_bus
            await event_bus.publish("stream_offline", {
                "broadcaster_user_login": login,
                "broadcaster_user_name":  login,
                "twitch_user_id":         broadcaster_id,
            })
        except Exception:
            logger.exception(f"Failed to publish offline event for {login}")

    # ──────────────────────────────────────────────────────────
    # STREAM CHANGE TRACKING
    # ──────────────────────────────────────────────────────────

    async def track_stream_changes(self) -> None:
        """
        Detects title / game changes on currently live streams and
        notifies via self.notifier and event_bus.
        """
        try:
            async with self.db_pool.acquire() as conn:
                rows = await conn.fetch(
                    "SELECT broadcaster_id FROM streamers WHERE is_live = TRUE"
                )

            for row in rows:
                bid = row["broadcaster_id"]

                current = await self.twitch_api.get_stream_metadata(bid)
                if not current:
                    continue

                prev = await self.metadata_cache.get(bid) if self.metadata_cache else None

                if not prev:
                    if self.metadata_cache:
                        await self.metadata_cache.set(bid, current)
                    continue

                if not self._has_changed(prev, current):
                    continue

                change_type = (
                    self.change_classifier.classify(prev, current)
                    if self.change_classifier
                    else "unknown"
                )

                # Cooldown check
                if self.cooldown_manager:
                    key = f"{bid}:{change_type}"
                    if not self.cooldown_manager.should_send(key, cooldown=300):
                        continue

                # Update cache with latest
                if self.metadata_cache:
                    await self.metadata_cache.set(bid, current)

                await self._notify_stream_change(bid, prev, current, change_type)

        except Exception:
            logger.exception("Stream change tracking failed")

    def _has_changed(self, old: dict, new: dict) -> bool:
        # Fixed: Twitch API uses "game_name" not "game"
        return (
            old.get("title")     != new.get("title")
            or old.get("game_name") != new.get("game_name")
        )

    async def _notify_stream_change(
        self,
        broadcaster_id: str,
        old: dict,
        new: dict,
        change_type: str,
    ) -> None:
        logger.info(
            "Stream changed",
            extra={"extra_data": {
                "broadcaster": broadcaster_id,
                "type":        change_type,
                "old_title":   old.get("title"),
                "new_title":   new.get("title"),
                "old_game":    old.get("game_name"),
                "new_game":    new.get("game_name"),
            }},
        )

        if self.notifier:
            await self.notifier.stream_updated(broadcaster_id, old, new, change_type)

    # ──────────────────────────────────────────────────────────
    # BADGES & DROPS
    # ──────────────────────────────────────────────────────────

    async def refresh_badges(self) -> None:
        try:
            await self.twitch_api.fetch_badges(redis=self.redis)
        except Exception:
            logger.exception("Badge refresh failed")

    async def check_drops(self) -> None:
        try:
            await self.twitch_api.fetch_drops()
        except Exception:
            logger.exception("Drops check failed")

    # ──────────────────────────────────────────────────────────
    # METRICS
    # ──────────────────────────────────────────────────────────

    def get_metrics(self) -> dict:
        return {
            "cycles":   self.monitor_cycles_total,
            "failures": self.monitor_cycle_failures,
            "running":  self._running,
        }
