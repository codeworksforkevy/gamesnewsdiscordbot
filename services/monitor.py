import asyncio
import logging
from datetime import datetime, timezone


class TwitchMonitor:

    LEADER_LOCK_ID = 987654321

    def __init__(
        self,
        twitch_api,
        eventsub_manager,
        db_pool,
        redis,
        notifier=None,
        telemetry=None,
        interval=180
    ):
        self.twitch_api = twitch_api
        self.eventsub_manager = eventsub_manager
        self.db_pool = db_pool
        self.redis = redis
        self.notifier = notifier
        self.telemetry = telemetry
        self.interval = interval

        self.logger = logging.getLogger("twitch-monitor")

        self._running = False

        self.monitor_cycles_total = 0
        self.monitor_cycle_failures = 0

    # ==================================================
    # LEADER LOCK
    # ==================================================

    async def acquire_leader_lock(self):
        try:
            async with self.db_pool.acquire() as conn:
                return await conn.fetchval(
                    "SELECT pg_try_advisory_lock($1);",
                    self.LEADER_LOCK_ID
                )
        except Exception:
            self.logger.exception("Leader lock acquisition failed")
            return False

    # ==================================================
    # START
    # ==================================================

    async def start(self):

        if self._running:
            return

        is_leader = await self.acquire_leader_lock()

        if not is_leader:
            self.logger.info("Not leader — monitor disabled.")
            return

        self._running = True
        self.logger.info("TwitchMonitor started (leader).")

        while self._running:
            try:
                await self.run_cycle()
            except Exception:
                self.logger.exception("Cycle crashed (loop continues)")

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
            await self.track_stream_changes()  # 🔥 NEW
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
    # EVENTSUB
    # ==================================================

    async def audit_eventsub_subscriptions(self):

        try:
            subs = await self.eventsub_manager.list_subscriptions()

            active_ids = {
                s.get("condition", {}).get("broadcaster_user_id")
                for s in subs or []
                if s.get("type") == "stream.online"
            }

            async with self.db_pool.acquire() as conn:
                rows = await conn.fetch("SELECT broadcaster_id FROM streamers;")

            db_ids = {r["broadcaster_id"] for r in rows}

            missing = db_ids - active_ids

            for broadcaster_id in missing:
                await self.eventsub_manager.subscribe_stream_online(
                    broadcaster_id,
                    self.eventsub_manager.callback_url
                )

        except Exception:
            self.logger.exception("EventSub audit failed")

    # ==================================================
    # LIVE STATE
    # ==================================================

    async def reconcile_live_state(self):

        try:
            async with self.db_pool.acquire() as conn:
                rows = await conn.fetch("""
                    SELECT broadcaster_id
                    FROM streamers
                    WHERE is_live = TRUE;
                """)

            broadcaster_ids = [r["broadcaster_id"] for r in rows]

            if not broadcaster_ids:
                return

            live_ids = await self.twitch_api.check_streams_live(
                broadcaster_ids
            )

            if not live_ids:
                return

            to_reset = [
                bid for bid in broadcaster_ids
                if bid not in live_ids
            ]

            if not to_reset:
                return

            async with self.db_pool.acquire() as conn:
                await conn.execute("""
                    UPDATE streamers
                    SET is_live = FALSE
                    WHERE broadcaster_id = ANY($1::text[]);
                """, to_reset)

        except Exception:
            self.logger.exception("Live state reconciliation failed")

    # ==================================================
    # 🔥 NEW: STREAM CHANGE TRACKING
    # ==================================================

    async def track_stream_changes(self):

        try:
            async with self.db_pool.acquire() as conn:
                rows = await conn.fetch("""
                    SELECT broadcaster_id, title, game_name
                    FROM streamers
                    WHERE is_live = TRUE;
                """)

            for row in rows:
                bid = row["broadcaster_id"]

                current = await self.twitch_api.get_stream_metadata(bid)
                if not current:
                    continue

                cache_key = f"stream:{bid}"

                prev = await self.redis.get(cache_key)

                # First time → just cache
                if not prev:
                    await self.redis.set(cache_key, current, ex=300)
                    continue

                # Compare
                if prev["title"] != current["title"] or prev["game"] != current["game"]:

                    await self.redis.set(cache_key, current, ex=300)

                    await self.notify_stream_change(
                        bid,
                        prev,
                        current
                    )

        except Exception:
            self.logger.exception("Stream change tracking failed")

    # ==================================================
    # 🔥 NOTIFICATION HOOK
    # ==================================================

    async def notify_stream_change(self, broadcaster_id, old, new):

        self.logger.info(
            "Stream changed",
            extra={"extra_data": {
                "broadcaster": broadcaster_id,
                "old": old,
                "new": new
            }}
        )

        if self.notifier:
            await self.notifier.stream_updated(
                broadcaster_id,
                old,
                new
            )

    # ==================================================
    # BADGES
    # ==================================================

    async def refresh_badges(self):

        try:
            await self.twitch_api.fetch_badges(
                redis=self.redis
            )
        except Exception:
            self.logger.exception("Badge refresh failed")

    # ==================================================
    # DROPS
    # ==================================================

    async def check_drops(self):

        try:
            await self.twitch_api.fetch_drops()
        except Exception:
            self.logger.exception("Drops check failed")

    # ==================================================
    # METRICS
    # ==================================================

    def get_metrics(self):

        return {
            "monitor_cycles_total": self.monitor_cycles_total,
            "monitor_cycle_failures": self.monitor_cycle_failures
        }
