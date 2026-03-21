# services/twitch_monitor.py

import asyncio
import logging
from datetime import datetime, timedelta

logger = logging.getLogger("twitch-monitor")


class TwitchMonitor:
    def __init__(self, bot, session, redis=None, interval=300):
        self.bot = bot
        self.session = session
        self.redis = redis

        self.interval = interval
        self._task = None
        self._running = False

        # fallback memory cache (redis yoksa)
        self._seen_events = set()

    # ==================================================
    # START / STOP
    # ==================================================

    def start(self):
        if not self._task:
            self._running = True
            self._task = asyncio.create_task(self._run())
            logger.info("TwitchMonitor started")

    def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()

    # ==================================================
    # MAIN LOOP
    # ==================================================

    async def _run(self):
        while self._running:
            try:
                await self.check_drops()
            except Exception as e:
                logger.exception("Twitch monitor loop failed", extra={"error": str(e)})

            await asyncio.sleep(self.interval)

    # ==================================================
    # CORE LOGIC
    # ==================================================

    async def check_drops(self):

        drops = await self.fetch_drops()

        for drop in drops:
            key = f"twitch_drop:{drop['id']}"

            if await self._is_duplicate(key):
                continue

            await self._mark_seen(key)

            await self.dispatch_drop(drop)

    # ==================================================
    # FETCH (stub - senin mevcut fetch logic bağlanacak)
    # ==================================================

    async def fetch_drops(self):
        """
        Bunu kendi twitch_drops fetch fonksiyonuna bağla
        """
        return []

    # ==================================================
    # DUPLICATE CONTROL
    # ==================================================

    async def _is_duplicate(self, key):

        # Redis varsa
        if self.redis:
            try:
                val = await self.redis.get(key)
                return val is not None
            except Exception:
                pass

        # fallback memory
        return key in self._seen_events

    async def _mark_seen(self, key):

        if self.redis:
            try:
                await self.redis.set(key, "1", ttl=3600)
                return
            except Exception:
                pass

        self._seen_events.add(key)

    # ==================================================
    # DISPATCH
    # ==================================================

    async def dispatch_drop(self, drop):
        try:
            logger.info(f"New Twitch Drop: {drop.get('title')}")

            # burada Discord gönderimi yapılır
            # örn: await channel.send(...)

        except Exception as e:
            logger.warning("Drop dispatch failed", extra={"error": str(e)})
