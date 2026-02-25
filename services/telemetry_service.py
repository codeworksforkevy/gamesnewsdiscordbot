
import asyncpg
import os
from datetime import datetime

class TelemetryService:

    def __init__(self):
        self.dsn = os.getenv("DATABASE_URL")
        self.pool = None

    async def init(self):
        self.pool = await asyncpg.create_pool(self.dsn)

    async def log_stream_snapshot(self, user, viewers, title, game):
        async with self.pool.acquire() as conn:
            await conn.execute(
                '''
                INSERT INTO stream_snapshots(user_login, viewer_count, title, game_name, recorded_at)
                VALUES($1, $2, $3, $4, $5)
                ''',
                user, viewers, title, game, datetime.utcnow()
            )
