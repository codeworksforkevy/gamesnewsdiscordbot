"""
Production TwitchMonitor — leader-elected, self-healing cycle.
Includes Watchdog mechanism for state reconciliation.
"""
import asyncio
import logging
from typing import Optional

from events.stream_events import KNOWN_STREAMERS

logger = logging.getLogger("twitch-monitor")


class TwitchMonitor:
    LEADER_LOCK_KEY = "twitch-monitor:leader"
    LEADER_LOCK_TTL = 60

    def __init__(self, twitch_api, eventsub_manager, db_pool, redis, bot, notifier):
        self.twitch_api = twitch_api
        self.eventsub = eventsub_manager
        self.db = db_pool
        self.redis = redis
        self.bot = bot
        self.notifier = notifier
        self._running = False
        self._task = None
        self.monitor_cycles_total = 0

    async def run_safety_check(self):
        """
        [Watchdog] Periodically verifies live status against Twitch API.
        If an EventSub notification was missed, triggers the notification pipeline.
        """
        try:
            # ── 1. Fetch tracked streamers from DB ───────────────────────────
            rows = await self.db.fetch(
                "SELECT DISTINCT twitch_login, twitch_user_id FROM streamers"
            )

            # ── 2. Merge with KNOWN_STREAMERS (same pattern as StreamMonitor) ─
            # Streamers not yet added via /live add are still monitored.
            db_logins = {r["twitch_login"] for r in rows}
            user_ids: list[str] = [
                str(r["twitch_user_id"]) for r in rows if r["twitch_user_id"]
            ]
            for login, uid in KNOWN_STREAMERS.items():
                if login not in db_logins and uid:
                    user_ids.append(str(uid))

            if not user_ids:
                return

            # ── 3. Batch-fetch live status from Twitch API ───────────────────
            # TwitchAPI only exposes get_streams_by_ids — no logins-based method.
            live_streams = await self.twitch_api.get_streams_by_ids(user_ids)

            # ── 4. Recovery: post notifications for any missed EventSub events ─
            for stream in live_streams:
                login      = stream["user_login"].lower()
                stream_id  = stream.get("id", "live")
                status_key = f"stream:status:{login}"

                already_tracked = await self.redis.get(status_key)
                if not already_tracked:
                    logger.warning(
                        f"[Watchdog] {login} is live but not in Redis — "
                        f"EventSub may have been missed. Triggering recovery."
                    )
                    # Store stream_id to match the pattern used by handle_stream_online
                    await self.redis.set(status_key, stream_id, ttl=3600)
                    await self.notifier.stream_online(stream)

        except Exception as e:
            logger.error(f"[Watchdog] Failed to run safety check: {e}", exc_info=True)

    async def _cycle(self):
        """Main monitoring loop."""
        while self._running:
            self.monitor_cycles_total += 1

            # Run safety check every 5 cycles (~5 minutes)
            if self.monitor_cycles_total % 5 == 0:
                await self.run_safety_check()

            await asyncio.sleep(60)

    async def start(self):
        self._running = True
        self._task = asyncio.create_task(self._cycle())

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
