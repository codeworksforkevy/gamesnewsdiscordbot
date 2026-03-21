import asyncio
import logging
from datetime import datetime, timezone


class TwitchMonitor:

    LEADER_LOCK_KEY = "twitch-monitor:leader"
    LEADER_LOCK_TTL = 60

    def __init__(
        self,
        twitch_api,
        eventsub_manager,
        db_pool,
        redis,
        notifier=None,
        metadata_cache=None,
        cooldown_manager=None,
        change_classifier=None,
        telemetry=None,
        interval=180
    ):
        self.twitch_api = twitch_api
        self.eventsub_manager = eventsub_manager
        self.db_pool = db_pool
        self.redis = redis

        self.notifier = notifier
        self.metadata_cache = metadata_cache
        self.cooldown_manager = cooldown_manager
        self.change_classifier = change_classifier
        self.telemetry = telemetry

        self.interval = interval

        self.logger = logging.getLogger("twitch-monitor")

        self._running = False

        self.monitor_cycles_total = 0
        self.monitor_cycle_failures = 0

    # ==================================================
    # LEADER ELECTION
    # ==================================================

    async def acquire_leader_lock(self):

        try:
            if self.redis:
                ok = await self.redis.set(
                    self.LEADER_LOCK_KEY,
                    "1",
                    nx=True,
                    ex=self.LEADER_LOCK_TTL
                )
                if ok:
                    return True

            # DB fallback (Postgres advisory lock)
            async with self.db_pool.acquire() as conn:
                return await conn.fetchval(
                    "SELECT pg_try_advisory_lock($1);",
                    987654321
                )

        except Exception:
            self.logger.exception("Leader lock failed")
            return False

    # ==================================================
    # START / STOP
    # ==================================================

    async def start(self):

        if self._running:
            return

        if not await self.acquire_leader_lock():
            self.logger.info("Not leader → monitor disabled")
            return

        self._running = True
        self.logger.info("TwitchMonitor started (leader)")

        while self._running:
            try:
                await self.run_cycle()
            except Exception:
                self.logger.exception("Cycle crashed")

            await asyncio.sleep(self.interval)

    async def stop(self):
        self._running = False

    # ==================================================
    # MAIN CYCLE
    # ==================================================

    async def run_cycle(self):

        self.monitor_cycles_total += 1
        start = datetime.now(timezone.utc)

        try:
            await self.audit_eventsub_subscriptions()
            await self.reconcile_live_state()
            await self.track_stream_changes()
            await self.refresh_badges()
            await self.check_drops()

            duration = (datetime.now(timezone.utc) - start).total_seconds()

            self.logger.info(
                "Monitor cycle completed",
                extra={"extra_data": {
                    "duration_sec": duration,
                    "cycle": self.monitor_cycles_total
                }}
            )

        except Exception:
            self.monitor_cycle_failures += 1
            self.logger.exception("Monitor cycle failed")

    # ==================================================
    # EVENTSUB SYNC
    # ==================================================

    async def audit_eventsub_subscriptions(self):

        try:
            subs = await self.eventsub_manager.list_subscriptions()

            active = {
                s.get("condition", {}).get("broadcaster_user_id")
                for s in subs or []
                if s.get("type") == "stream.online"
            }

            async with self.db_pool.acquire() as conn:
                rows = await conn.fetch("SELECT broadcaster_id FROM streamers")

            db_ids = {r["broadcaster_id"] for r in rows}
            missing = db_ids - active

            for bid in missing:
                await self.eventsub_manager.subscribe_stream_online(
                    bid,
                    self.eventsub_manager.callback_url
                )

        except Exception:
            self.logger.exception("EventSub audit failed")

    # ==================================================
    # LIVE STATE RECONCILIATION
    # ==================================================

    async def reconcile_live_state(self):

        try:
            async with self.db_pool.acquire() as conn:
                rows = await conn.fetch("""
                    SELECT broadcaster_id
                    FROM streamers
                    WHERE is_live = TRUE;
                """)

            ids = [r["broadcaster_id"] for r in rows]

            if not ids:
                return

            live_ids = await self.twitch_api.check_streams_live(ids)

            if not live_ids:
                return

            to_reset = [bid for bid in ids if bid not in live_ids]

            if not to_reset:
                return

            async with self.db_pool.acquire() as conn:
                await conn.execute("""
                    UPDATE streamers
                    SET is_live = FALSE
                    WHERE broadcaster_id = ANY($1::text[]);
                """, to_reset)

        except Exception:
            self.logger.exception("Live reconciliation failed")

    # ==================================================
    # STREAM CHANGE TRACKING
    # ==================================================

    async def track_stream_changes(self):

        try:
            async with self.db_pool.acquire() as conn:
                rows = await conn.fetch("""
                    SELECT broadcaster_id
                    FROM streamers
                    WHERE is_live = TRUE;
                """)

            for row in rows:

                bid = row["broadcaster_id"]

                current = await self.twitch_api.get_stream_metadata(bid)
                if not current:
                    continue

                prev = None

                if self.metadata_cache:
                    prev = await self.metadata_cache.get(bid)

                if not prev:
                    if self.metadata_cache:
                        await self.metadata_cache.set(bid, current)
                    continue

                if not self._has_changed(prev, current):
                    continue

                change_type = (
                    self.change_classifier.classify(prev, current)
                    if self.change_classifier else "unknown"
                )

                # cooldown
                if self.cooldown_manager:
                    key = f"{bid}:{change_type}"

                    if not self.cooldown_manager.should_send(key, cooldown=300):
                        continue

                # update cache
                if self.metadata_cache:
                    await self.metadata_cache.set(bid, current)

                await self.notify_stream_change(
                    bid,
                    prev,
                    current,
                    change_type
                )

        except Exception:
            self.logger.exception("Stream tracking failed")

    # ==================================================
    # DIFF LOGIC
    # ==================================================

    def _has_changed(self, old, new):

        return (
            old.get("title") != new.get("title")
            or old.get("game") != new.get("game")
        )

    # ==================================================
    # NOTIFIER
    # ==================================================

    async def notify_stream_change(self, broadcaster_id, old, new, change_type):

        self.logger.info(
            "Stream changed",
            extra={"extra_data": {
                "broadcaster": broadcaster_id,
                "type": change_type
            }}
        )

        if self.notifier:
            await self.notifier.stream_updated(
                broadcaster_id,
                old,
                new,
                change_type
            )

    # ==================================================
    # BADGES
    # ==================================================

    async def refresh_badges(self):

        try:
            await self.twitch_api.fetch_badges(redis=self.redis)
        except Exception:
            self.logger.exception("Badge refresh failed")

    # ==================================================
    # DROPS
    # ==================================================

    async def check_drops(self):

        try:
            await self.twitch_api.fetch_drops()
        except Exception:
            self.logger.exception("Drops failed")

    # ==================================================
    # METRICS
    # ==================================================

    def get_metrics(self):

        return {
            "cycles": self.monitor_cycles_total,
            "failures": self.monitor_cycle_failures
        }
