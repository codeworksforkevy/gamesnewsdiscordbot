# core/state_manager.py

from typing import Optional
import asyncpg


class AppState:
    """
    Central application state (event-driven architecture core)
    """

    def __init__(self):
        self.db_pool: Optional[asyncpg.Pool] = None
        self.redis = None  # optional
        self.bot = None

    def set_db_pool(self, pool: asyncpg.Pool):
        self.db_pool = pool

    def get_db_pool(self) -> asyncpg.Pool:
        if not self.db_pool:
            raise RuntimeError("DB pool not initialized in AppState")
        return self.db_pool


# Global instance
state = AppState()
