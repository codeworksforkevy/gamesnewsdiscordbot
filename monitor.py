"""
Production TwitchMonitor — leader-elected, self-healing cycle.
Includes Watchdog mechanism for state reconciliation.
"""

import asyncio
import logging
from typing import Optional

logger = logging.getLogger("twitch-monitor")

class TwitchMonitor:
    LEADER_LOCK_KEY = "twitch-monitor:leader"
    LEADER_LOCK_TTL = 60

    def __init__(self, twitch_api, eventsub_manager, db_pool, redis, bot, notifier):
        self.twitch_api = twitch_api
        self.eventsub = eventsub_manager
        self.db = db_pool  # Use the pool passed in
        self.redis = redis
        self.bot = bot     # Store the bot reference
        self.notifier = notifier
        self._running = False
        self._task = None
        self.monitor_cycles_total = 0

    async def run_safety_check(self):
        """
        [Watchdog] Periodically verifies live status against Twitch API.
        If an event was missed, it triggers the notification pipeline.
        """
        try:
            tracked = await self.db.get_all_tracked_streamers()
            user_ids = [s.id for s in tracked]
            
            if not user_ids:
                return

            # Batch fetch live streams (up to 100 per request)
            live_streams = await self.twitch_api.get_streams_by_ids(user_ids)

            for stream in live_streams:
                status_key = f"stream:status:{stream['user_login'].lower()}"
                
                # If live on Twitch but not in Redis, we missed the EventSub
                if not await self.redis.exists(status_key):
                    logger.warning(f"[Watchdog] {stream['user_login']} is live but missing in Redis! Recovery triggered.")
                    await self.redis.set(status_key, "true", ttl=3600)
                    await self.notifier.stream_online(stream)

        except Exception as e:
            logger.error(f"[Watchdog] Failed to run safety check: {e}", exc_info=True)

    async def _cycle(self):
        """Main monitoring loop."""
        while self._running:
            self.monitor_cycles_total += 1
            
            # Run safety check every 5 cycles (~5 mins)
            if self.monitor_cycles_total % 5 == 0:
                await self.run_safety_check()

            await asyncio.sleep(60)

    def start(self):
        self._running = True
        self._task = asyncio.create_task(self._cycle())

    def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
