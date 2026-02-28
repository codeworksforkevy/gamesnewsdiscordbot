import asyncio
import logging
from datetime import datetime, timezone


class TwitchMonitor:

    LEADER_LOCK_ID = 987654321  # advisory lock key

    def __init__(
        self,
        twitch_api,
        eventsub_manager,
        db_pool,
        telemetry=None,
        interval=180
    ):
        self.twitch_api = twitch_api
        self.eventsub_manager = eventsub_manager
        self.db_pool = db_pool
        self.telemetry = telemetry
        self.interval = interval
        self.logger = logging.getLogger("twitch-monitor")
        self._running = False

        # Metrics
        self.monitor_cycles_total = 0
        self.monitor_cycle_failures = 0

    # ==================================================
    # LEADER LOCK (Multi-instance Safe)
    # ==================================================

    async def acquire_leader_lock(self):

        async with self.db_pool.acquire() as conn:
            result = await conn.fetchval(
                "SELECT pg_try_advisory_lock($1);",
                self.LEADER_LOCK_ID
            )

        return result

    # ==================================================
    # MAIN LOOP
    # ==================================================

    async def start(self):

        if self._running:
            return

        # Leader election
        is_leader = await self.acquire_leader_lock()

        if not is_leader:
            self.logger.info(
                "Monitor not leader — disabled on this instance."
            )
            return

        self._running = True

        self.logger.info(
            "TwitchMonitor started (leader)."
        )

        try:
            while self._running:
                await self.run_cycle()
                await asyncio.sleep(self.interval)

        except asyncio.CancelledError:
            self.logger.info("TwitchMonitor cancelled.")
            raise

        finally:
            self._running = False

    async def stop(self):
        self._running = False
        self.logger.info("TwitchMonitor stopped.")

    # ==================================================
    # SINGLE CYCLE
    # ==================================================

    async def run_cycle(self):

        cycle_start = datetime.now(timezone.utc)
        self.monitor_cycles_total += 1

        try:
            await self.audit_eventsub_subscriptions()
            await self.reconcile_live_state()
            await self.refresh_badges()
            await self.check_drops()

            duration = (
                datetime.now(timezone.utc) - cycle_start
            ).total_seconds()

            self.logger.info(
                "Monitor cycle completed",
                extra={
                    "extra_data": {
                        "duration_sec": duration,
                        "cycle": self.monitor_cycles_total
                    }
                }
            )

        except Exception as e:

            self.monitor_cycle_failures += 1

            self.logger.exception(
                "Monitor cycle failed",
                extra={
                    "extra_data": {
                        "error": str(e),
                        "failures": self.monitor_cycle_failures
                    }
                }
            )

    # ==================================================
    # EVENTSUB AUDIT
    # ==================================================

    async def audit_eventsub_subscriptions(self):

        subs = await self.eventsub_manager.list_subscriptions()

        active_ids = {
            s["condition"]["broadcaster_user_id"]
            for s in subs
            if s.get("type") == "stream.online"
        }

        async with self.db_pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT DISTINCT broadcaster_id FROM streamers;"
            )

        db_ids = {r["broadcaster_id"] for r in rows}
        missing = db_ids - active_ids

        if missing:
            self.logger.warning(
                "Missing EventSub subscriptions",
                extra={
                    "extra_data": {
                        "missing_count": len(missing)
                    }
                }
            )

        for broadcaster_id in missing:
            await self.eventsub_manager.ensure_stream_subscriptions(
                broadcaster_id
            )

    # ==================================================
    # LIVE STATE RECONCILIATION
    # ==================================================

    async def reconcile_live_state(self):

        async with self.db_pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT broadcaster_id
                FROM streamers
                WHERE is_live = TRUE;
            """)

        if not rows:
            return

        broadcaster_ids = [r["broadcaster_id"] for r in rows]

        if len(broadcaster_ids) > 100:
            self.logger.warning(
                "Streamer count exceeds 100. Truncating batch."
            )
            broadcaster_ids = broadcaster_ids[:100]

        live_ids = await self.twitch_api.check_streams_live(
            broadcaster_ids
        )

        if live_ids is None:
            self.logger.warning("Live check failed — skipping reset.")
            return

        to_reset = [
            bid for bid in broadcaster_ids
            if bid not in live_ids
        ]

        if not to_reset:
            return

        self.logger.info(
            "Resetting drifted live states",
            extra={
                "extra_data": {
                    "count": len(to_reset)
                }
            }
        )

        async with self.db_pool.acquire() as conn:
            await conn.execute("""
                UPDATE streamers
                SET is_live = FALSE
                WHERE broadcaster_id = ANY($1::text[]);
            """, to_reset)

    # ==================================================
    # BADGE REFRESH
    # ==================================================

    async def refresh_badges(self):

        try:
            await self.twitch_api.fetch_badges()
        except Exception as e:
            self.logger.warning(
                "Badge refresh failed",
                extra={"extra_data": {"error": str(e)}}
            )

    # ==================================================
    # DROPS CHECK
    # ==================================================

    async def check_drops(self):

        try:
            await self.twitch_api.fetch_drops()
        except Exception as e:
            self.logger.warning(
                "Drops check failed",
                extra={"extra_data": {"error": str(e)}}
            )

    # ==================================================
    # METRICS EXPORT
    # ==================================================

    def get_metrics(self):

        return {
            "monitor_cycles_total": self.monitor_cycles_total,
            "monitor_cycle_failures": self.monitor_cycle_failures
        }
