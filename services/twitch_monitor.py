# services/twitch_monitor.py
#
# Düzeltmeler:
# - Yalnızca went-live detect ediyordu, went-offline yoktu — eklendi
# - event_bus.emit → event_bus.publish (event_bus.py ile tutarlı)
# - Her iki event de broadcaster_user_login/name alanlarıyla yayınlanıyor
#   böylece event_router doğru alanları bulabiliyor

import asyncio
import logging
from datetime import datetime, timezone

logger = logging.getLogger("twitch-monitor")


class TwitchMonitor:

    def __init__(self, bot, app_state, interval: int = 60):
        self.bot       = bot
        self.app_state = app_state
        self.interval  = interval
        self._running  = False
        self._task     = None

    def start(self) -> None:
        if not self._running:
            self._running = True
            self._task    = asyncio.create_task(self._loop())
            logger.info("TwitchMonitor başlatıldı")

    def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            logger.info("TwitchMonitor durduruldu")

    async def _loop(self) -> None:
        while self._running:
            try:
                await self.check_streams()
            except Exception as e:
                logger.error(f"Monitor hatası: {e}", exc_info=True)
            await asyncio.sleep(self.interval)

    async def check_streams(self) -> None:
        db         = self.app_state.db
        twitch_api = self.app_state.twitch_api

        rows = await db.fetch("SELECT broadcaster_id, twitch_login FROM streamers")

        for row in rows:
            user_id = row["broadcaster_id"]
            login   = row["twitch_login"]

            try:
                stream = await twitch_api.get_stream(user_id)

                prev     = await db.fetchrow(
                    "SELECT is_live FROM streamer_states WHERE twitch_user_id = $1",
                    user_id,
                )
                was_live = prev["is_live"] if prev else False
                is_live  = bool(stream)

                # Went live
                if not was_live and is_live:
                    logger.info(f"{login} CANLI!")
                    await self._emit_online(user_id, login, stream)

                # Went offline
                elif was_live and not is_live:
                    logger.info(f"{login} yayını bitirdi")
                    await self._emit_offline(user_id, login)

                # Durumu güncelle
                await db.execute(
                    """
                    INSERT INTO streamer_states (
                        twitch_user_id, is_live, title, game_name, viewer_count, last_updated
                    )
                    VALUES ($1, $2, $3, $4, $5, $6)
                    ON CONFLICT (twitch_user_id) DO UPDATE SET
                        is_live      = EXCLUDED.is_live,
                        title        = EXCLUDED.title,
                        game_name    = EXCLUDED.game_name,
                        viewer_count = EXCLUDED.viewer_count,
                        last_updated = EXCLUDED.last_updated
                    """,
                    user_id, is_live,
                    stream.get("title")        if stream else None,
                    stream.get("game_name")    if stream else None,
                    stream.get("viewer_count") if stream else None,
                    datetime.now(timezone.utc),
                )

            except Exception as e:
                logger.warning(f"Streamer kontrolü başarısız — {login}: {e}")

    async def _emit_online(self, user_id: str, login: str, stream: dict) -> None:
        from core.event_bus import event_bus
        await event_bus.publish("stream_online", {
            "twitch_user_id":         user_id,
            "twitch_login":           login,
            "broadcaster_user_login": login,
            "broadcaster_user_name":  login,
            "stream":                 stream,
        })

    async def _emit_offline(self, user_id: str, login: str) -> None:
        from core.event_bus import event_bus
        await event_bus.publish("stream_offline", {
            "twitch_user_id":         user_id,
            "twitch_login":           login,
            "broadcaster_user_login": login,
            "broadcaster_user_name":  login,
        })
