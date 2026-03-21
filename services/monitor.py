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
    # LEADER LOCK
    # ==================================================

    async def acquire_leader_lock(self):

        try:
            async with self.db_pool.acquire() as conn:
                result = await conn.fetchval(
                    "SELECT pg_try_advisory_lock($1);",
                    self.LEADER_LOCK_ID
                )
            return result

        except Exception:
            self.logger.exception("Leader lock acquisition failed")
            return False

    # ==================================================
    # START LOOP
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

        try:
            while self._running:
                await self.run_cycle()
                await asyncio.sleep(self.interval)

        except asyncio.CancelledError:
            self.logger.info("TwitchMonitor cancelled.")
            raise

        except Exception:
            self.logger.exception("Fatal monitor loop error")

        finally:
            self._running = False

    async def stop(self):
        self._running = False
        self.logger.info("TwitchMonitor stopped.")

    # ==================================================
    # CYCLE
    # ==================================================

    async def run_cycle(self):

        start = datetime.now(timezone.utc)
        self.monitor_cycles_total += 1

        try:
            await self.audit_eventsub_subscriptions()
            await self.reconcile_live_state()
            await self.refresh_badges()
            await self.check_drops()

            duration = (
                datetime.now(timezone.utc) - start
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
                rows = await conn.fetch(
                    "SELECT broadcaster_id FROM streamers;"
                )

            db_ids = {r["broadcaster_id"] for r in rows}

            missing = db_ids - active_ids

            if missing:
                self.logger.warning(
                    "Missing EventSub subscriptions",
                    extra={"extra_data": {"missing": list(missing)}}
                )

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

            if not rows:
                return

            broadcaster_ids = [r["broadcaster_id"] for r in rows]

            if not broadcaster_ids:
                return

            if len(broadcaster_ids) > 100:
                broadcaster_ids = broadcaster_ids[:100]

            live_ids = await self.twitch_api.check_streams_live(
                broadcaster_ids
            )

            if not live_ids:
                self.logger.warning("Live check failed or empty result")
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

            self.logger.info(
                "Live state reconciled",
                extra={"extra_data": {"reset_count": len(to_reset)}}
            )

        except Exception:
            self.logger.exception("Live state reconciliation failed")

    # ==================================================
    # BADGES
    # ==================================================

    async def refresh_badges(self):

        try:
            await self.twitch_api.fetch_badges()
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
