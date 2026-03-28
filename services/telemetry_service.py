# services/telemetry_service.py
#
# Düzeltmeler:
# - Kendi asyncpg pool'unu açıyordu (kaynak israfı) — app_state.db kullanıyor
# - datetime.utcnow() deprecated — datetime.now(timezone.utc) kullanıyor
# - stream_snapshots tablosu yoksa sessizce devam ediyor

import logging
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger("telemetry")


class TelemetryService:

    def __init__(self, db=None):
        self.db = db   # services.db.Database instance (app_state.db)

    async def init(self, db=None) -> None:
        """db parametresi geriye dönük uyumluluk için korundu."""
        if db:
            self.db = db
        # stream_snapshots tablosunu oluştur (yoksa)
        if self.db:
            try:
                await self.db.execute("""
                    CREATE TABLE IF NOT EXISTS stream_snapshots (
                        id          BIGSERIAL   PRIMARY KEY,
                        user_login  TEXT        NOT NULL,
                        viewer_count INTEGER,
                        title       TEXT,
                        game_name   TEXT,
                        recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                """)
            except Exception as e:
                logger.warning(f"stream_snapshots tablosu oluşturulamadı: {e}")

    async def log_stream_snapshot(
        self,
        user: str,
        viewers: Optional[int],
        title: Optional[str],
        game: Optional[str],
    ) -> None:
        if not self.db:
            logger.warning("TelemetryService: DB bağlı değil")
            return
        try:
            await self.db.execute(
                """
                INSERT INTO stream_snapshots (user_login, viewer_count, title, game_name, recorded_at)
                VALUES ($1, $2, $3, $4, $5)
                """,
                user, viewers, title, game, datetime.now(timezone.utc),
            )
        except Exception as e:
            logger.error(f"Telemetry snapshot hatası — {user}: {e}")
