import asyncio
import logging
from datetime import datetime, timezone


class TwitchMonitor:

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

    # ==================================================
    # MAIN LOOP (CANCEL SAFE)
    # ==================================================

    async def start(self):

        if self._running:
            return

        self._running = True
        self.logger.info("TwitchMonitor started.")

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

        try:
            await self.audit_eventsub_subscriptions()
            await self.reconcile_live_state()
            await self.refresh_badges()
            await self.check_drops()

            duration = (
                datetime.now(timezone.utc) - cycle_start
            ).total_seconds()

            if self.telemetry:
                self.telemetry.record(
                    "monitor_cycle_success",
                    duration=duration
                )

            self.logger.info(
                "Monitor cycle completed in %.2fs",
                duration
            )

        except Exception as e:
            self.logger.exception("Monitor cycle failed: %s", e)

            if self.telemetry:
                self.telemetry.record("monitor_cycle_failure")

    # ==================================================
    # EVENTSUB AUDIT
    # ==================================================

    async def audit_eventsub_subscriptions(self):

        subs = await self.eventsub_manager.list_subscriptions()

        # Sadece stream.online subscription'ları dikkate al
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
                "Missing %d EventSub subscriptions.",
                len(missing)
            )

        for broadcaster_id in missing:
            await self.eventsub_manager.ensure_stream_subscriptions(
                broadcaster_id
            )

    # ==================================================
    # LIVE STATE RECONCILIATION (BATCH + SAFE)
    # ==================================================

    async def reconcile_live_state(self):

        # Sadece is_live = TRUE olanları çek (daha az iş)
        async with self.db_pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT broadcaster_id
                FROM streamers
                WHERE is_live = TRUE;
            """)

        if not rows:
            return

        broadcaster_ids = [r["broadcaster_id"] for r in rows]

        # Twitch batch limiti 100
        if len(broadcaster_ids) > 100:
            self.logger.warning(
                "Streamer count exceeds 100. Truncating batch."
            )
            broadcaster_ids = broadcaster_ids[:100]

        live_ids = await self.twitch_api.check_streams_live(
            broadcaster_ids
        )

        # Eğer API fail olduysa reset yapma
        if live_ids is None:
            self.logger.warning("Live check failed. Skipping reconciliation.")
            return

        to_reset = [
            broadcaster_id
            for broadcaster_id in broadcaster_ids
            if broadcaster_id not in live_ids
        ]

        if not to_reset:
            return

        self.logger.info(
            "Resetting %d drifted live states.",
            len(to_reset)
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
            badges = await self.twitch_api.fetch_badges()

            if self.telemetry:
                self.telemetry.record(
                    "badge_refresh",
                    count=len(badges)
                )

        except Exception as e:
            self.logger.warning("Badge refresh failed: %s", e)

    # ==================================================
    # DROPS CHECK
    # ==================================================

    async def check_drops(self):

        try:
            drops = await self.twitch_api.fetch_drops()

            if self.telemetry:
                self.telemetry.record(
                    "drops_check",
                    count=len(drops)
                )

        except Exception as e:
            self.logger.warning("Drops check failed: %s", e)
