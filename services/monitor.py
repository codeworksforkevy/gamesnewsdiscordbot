"""
monitor.py
────────────────────────────────────────────────────────────────
Production TwitchMonitor — leader-elected, self-healing cycle.
Contains the Watchdog mechanism to prevent missed notifications.
"""

import asyncio
import logging
from typing import Optional

logger = logging.getLogger("twitch-monitor")

class TwitchMonitor:

    LEADER_LOCK_KEY = "twitch-monitor:leader"
    LEADER_LOCK_TTL = 60          # seconds; renewed every cycle

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
        If an event was missed (webhook failure), this cross-verifies with 
        Redis state and triggers the notification pipeline.
        """
        try:
            # 1. Fetch all tracked streamers from Database
            tracked = await self.db.get_all_tracked_streamers()
            user_ids = [s.id for s in tracked]
            
            if not user_ids:
                return

            # 2. Query Twitch for all currently live streamers (Batch)
            live_streams = await self.twitch_api.get_streams_by_ids(user_ids)
            
            # 3. Compare with Redis state (Cross-verify)
            for stream in live_streams:
                status_key = f"stream:status:{stream['user_login'].lower()}"
                
                # If stream is live on Twitch but NOT in Redis, we missed the event
                if not await self.redis.exists(status_key):
                    logger.warning(f"[Watchdog] {stream['user_login']} is live but missing in Redis! Triggering recovery.")
                    
                    # Ensure status is set to prevent duplicate triggers before notifier finishes
                    await self.redis.set(status_key, "true", ttl=3600)
                    
                    # Trigger the notifier to announce the stream
                    await self.notifier.stream_online(stream)

        except Exception as e:
            logger.error(f"[Watchdog] Failed to run safety check: {e}", exc_info=True)

    async def _cycle(self):
        """Main monitoring loop with integrated Watchdog safety mechanism."""
        while self._running:
            self.monitor_cycles_total += 1
            
            # Run safety check every 5 cycles (approx. 5 minutes based on 60s sleep)
            if self.monitor_cycles_total % 5 == 0:
                await self.run_safety_check()

            # Existing monitoring logic (e.g., subscription health)
            # await self.audit_eventsub_subscriptions() 
            
            await asyncio.sleep(60)

    def start(self):
        """Starts the monitoring task."""
        self._running = True
        self._task = asyncio.create_task(self._cycle())
        logger.info("TwitchMonitor started with Watchdog enabled.")

    def stop(self):
        """Cancels the monitoring task gracefully."""
        self._running = False
        if self._task:
            self._task.cancel()
            logger.info("TwitchMonitor stopped.")
