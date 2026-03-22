# services/twitch_monitor.py

import asyncio
import logging
from datetime import datetime, timezone

logger = logging.getLogger("twitch-monitor")


class TwitchMonitor:

    def __init__(self, bot, app_state, interval=60):
        self.bot = bot
        self.app_state = app_state
        self.interval = interval

        self._running = False
        self._task = None

    # ==================================================
    # START / STOP
    # ==================================================

    def start(self):
        if not self._running:
            self._running = True
            self._task = asyncio.create_task(self._loop())
            logger.info("TwitchMonitor started")

    def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()

    # ==================================================
    # MAIN LOOP
    # ==================================================

    async def _loop(self):
        while self._running:
            try:
                await self.check_streams()
            except Exception as e:
                logger.error(f"Monitor error: {e}")

            await asyncio.sleep(self.interval)

    # ==================================================
    # CORE LOGIC
    # ==================================================

    async def check_streams(self):

        db = self.app_state.db
        twitch_api = self.app_state.twitch_api

        rows = await db.fetch(
            """
            SELECT twitch_user_id, twitch_login
            FROM streamers
            """
        )

        for row in rows:
            user_id = row["twitch_user_id"]
            login = row["twitch_login"]

            try:
                stream = await twitch_api.get_stream(user_id)

                # =========================
                # LOAD PREVIOUS STATE
                # =========================
                prev = await db.fetchrow(
                    """
                    SELECT is_live
                    FROM streamer_states
                    WHERE twitch_user_id = $1
                    """,
                    user_id
                )

                was_live = prev["is_live"] if prev else False
                is_live = bool(stream)

                # =========================
                # STATE CHANGE DETECTED
                # =========================
                if not was_live and is_live:

                    logger.info(f"{login} went LIVE")

                    await self.handle_stream_online(user_id, login, stream)

                # =========================
                # UPDATE STATE
                # =========================
                await db.execute(
                    """
                    INSERT INTO streamer_states (
                        twitch_user_id, is_live, title, game_name, viewer_count, last_updated
                    )
                    VALUES ($1, $2, $3, $4, $5, $6)
                    ON CONFLICT (twitch_user_id)
                    DO UPDATE SET
                        is_live = EXCLUDED.is_live,
                        title = EXCLUDED.title,
                        game_name = EXCLUDED.game_name,
                        viewer_count = EXCLUDED.viewer_count,
                        last_updated = EXCLUDED.last_updated
                    """,
                    user_id,
                    is_live,
                    stream.get("title") if stream else None,
                    stream.get("game_name") if stream else None,
                    stream.get("viewer_count") if stream else None,
                    datetime.now(timezone.utc)
                )

            except Exception as e:
                logger.warning(f"Streamer check failed: {login} → {e}")

    # ==================================================
    # EVENT EMIT
    # ==================================================

    async def handle_stream_online(self, user_id, login, stream):

        from core.event_bus import event_bus

        await event_bus.emit("stream_online", {
            "twitch_user_id": user_id,
            "twitch_login": login,
            "stream": stream
        })
