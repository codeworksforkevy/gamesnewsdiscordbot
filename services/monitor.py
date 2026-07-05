# monitor.py

import asyncio
import logging
from typing import Optional

logger = logging.getLogger("twitch-monitor")

class TwitchMonitor:
    LEADER_LOCK_KEY = "twitch-monitor:leader"
    LEADER_LOCK_TTL = 60

    def __init__(self, twitch_api, eventsub_manager, db, redis, notifier):
        self.twitch_api = twitch_api
        self.eventsub   = eventsub_manager
        self.db         = db
        self.redis      = redis
        self.notifier   = notifier
        self._running   = False
        self._task      = None
        self.monitor_cycles_total = 0

    async def run_safety_check(self):
        """
        [Watchdog] Periodically verifies live status against Twitch API.
        If an event was missed, it triggers the notification pipeline.
        """
        try:
            # 1. Fetch all tracked streamers from DB
            tracked = await self.db.get_all_tracked_streamers()
            user_ids = [s.id for s in tracked]
            
            # 2. Query Twitch for all currently live streamers
            live_streams = await self.twitch_api.get_streams_by_ids(user_ids)
            live_logins = {s["user_login"].lower() for s in live_streams}

            # 3. Compare with Redis state (Cross-verify)
            for stream in live_streams:
                status_key = f"stream:status:{stream['user_login'].lower()}"
                if not await self.redis.exists(status_key):
                    logger.warning(f"[Watchdog] {stream['user_login']} is live but not in Redis! Triggering alert.")
                    # Trigger the notifier (Assuming your notifier handles the announcement)
                    await self.notifier.stream_online(stream) 

        except Exception as e:
            logger.error(f"[Watchdog] Failed to run safety check: {e}")

    async def _cycle(self):
        while self._running:
            self.monitor_cycles_total += 1
            
            # Run safety check every 5 cycles (approx 5-10 mins)
            if self.monitor_cycles_total % 5 == 0:
                await self.run_safety_check()

            # ... (mevcut monitor döngü mantığın burada devam eder)
            await asyncio.sleep(60)

    def start(self):
        self._running = True
        self._task = asyncio.create_task(self._cycle())

    def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
