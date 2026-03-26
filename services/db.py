import os
import asyncpg
import logging

logger = logging.getLogger("database")


class Database:
    """
    Thin asyncpg wrapper.

    FIX: Added fetch(), fetchrow(), and execute() convenience methods.
    Previously the class only exposed get_pool() — every caller that did
    db.fetch(...) or db.fetchrow(...) crashed with AttributeError, which
    caused the "Startup error in guild" messages in Railway logs.
    """

    def __init__(self, dsn: str):
        self.dsn = dsn
        self.pool: asyncpg.Pool | None = None

    async def connect(self):
        if self.pool:
            return

        logger.info("Creating PostgreSQL pool...")

        self.pool = await asyncpg.create_pool(
            self.dsn,
            min_size=2,
            max_size=10,
            command_timeout=30,
        )

        # Run schema bootstrap on first connect
        await self._bootstrap()

        logger.info("Database initialized.")

    async def _bootstrap(self):
        """
        Ensure all required tables exist.
        Safe to run on every startup — all statements use IF NOT EXISTS.
        """
        async with self.pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS guild_configs (
                    guild_id            BIGINT PRIMARY KEY,
                    announce_channel_id BIGINT,
                    ping_role_id        BIGINT,
                    live_role_id        BIGINT,
                    notify_enabled      BOOLEAN DEFAULT TRUE,
                    enable_epic         BOOLEAN DEFAULT TRUE,
                    enable_gog          BOOLEAN DEFAULT TRUE,
                    enable_steam        BOOLEAN DEFAULT TRUE,
                    created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS guild_settings (
                    guild_id            BIGINT PRIMARY KEY,
                    announce_channel_id BIGINT,
                    created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS streamers (
                    id             SERIAL PRIMARY KEY,
                    guild_id       BIGINT NOT NULL,
                    twitch_user_id TEXT   NOT NULL,
                    twitch_login   TEXT   NOT NULL,
                    created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE (guild_id, twitch_user_id)
                );

                CREATE INDEX IF NOT EXISTS idx_streamers_guild
                    ON streamers (guild_id);

                CREATE TABLE IF NOT EXISTS streamer_states (
                    twitch_user_id TEXT PRIMARY KEY,
                    is_live        BOOLEAN DEFAULT FALSE,
                    title          TEXT,
                    game_name      TEXT,
                    viewer_count   INTEGER,
                    last_updated   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS user_notify_subscriptions (
                    id           SERIAL PRIMARY KEY,
                    user_id      BIGINT NOT NULL,
                    guild_id     BIGINT NOT NULL,
                    twitch_login TEXT   NOT NULL,
                    created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE (user_id, guild_id, twitch_login)
                );

                CREATE INDEX IF NOT EXISTS idx_notify_guild_login
                    ON user_notify_subscriptions (guild_id, twitch_login);

                CREATE TABLE IF NOT EXISTS stream_history (
                    id           SERIAL PRIMARY KEY,
                    guild_id     BIGINT NOT NULL,
                    twitch_login TEXT   NOT NULL,
                    started_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    ended_at     TIMESTAMP,
                    peak_viewers INTEGER DEFAULT 0,
                    title        TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_stream_history_guild_login
                    ON stream_history (guild_id, twitch_login);
            """)

    # ==================================================
    # CONVENIENCE METHODS
    # These match the asyncpg connection API so callers
    # can use db.fetch(...) instead of pool.acquire() everywhere.
    # ==================================================

    async def fetch(self, query: str, *args) -> list:
        """Fetch multiple rows. Returns list of Records."""
        async with self.pool.acquire() as conn:
            return await conn.fetch(query, *args)

    async def fetchrow(self, query: str, *args):
        """Fetch a single row. Returns Record or None."""
        async with self.pool.acquire() as conn:
            return await conn.fetchrow(query, *args)

    async def fetchval(self, query: str, *args):
        """Fetch a single value from the first column of the first row."""
        async with self.pool.acquire() as conn:
            return await conn.fetchval(query, *args)

    async def execute(self, query: str, *args) -> str:
        """Execute a statement. Returns status string e.g. 'INSERT 0 1'."""
        async with self.pool.acquire() as conn:
            return await conn.execute(query, *args)

    async def executemany(self, query: str, args_list: list) -> None:
        """Execute a statement for each set of args in args_list."""
        async with self.pool.acquire() as conn:
            await conn.executemany(query, args_list)

    # ==================================================
    # POOL ACCESS (kept for backward compat)
    # ==================================================

    def get_pool(self) -> asyncpg.Pool:
        if not self.pool:
            raise RuntimeError("Database not initialized.")
        return self.pool

    async def close(self):
        if self.pool:
            await self.pool.close()
            self.pool = None
            logger.info("Database pool closed.")
