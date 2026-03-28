-- =============================================================================
-- 001_init.sql
-- Initial schema — run once on a fresh database.
-- =============================================================================
-- ISSUES FIXED vs original:
--
-- 1. streamers had channel_id / role_id as columns — but the whole codebase
--    (guild_settings.py, event_router.py, stream_events.py) reads these from
--    guild_configs, not from the streamers row. Storing them per-streamer row
--    means every streamer would need its own channel/role configured, which
--    contradicts the guild-level config pattern used everywhere. Columns
--    removed from streamers; guild_configs is the single source of truth.
--
-- 2. guild_config table (singular) was created here, but every Python file
--    queries guild_configs (plural) with a completely different column set
--    (announce_channel_id, games_channel_id, ping_role_id, live_role_id,
--    notify_enabled, enable_ping, enable_epic, enable_gog, enable_steam).
--    The old guild_config table would never be found by any query.
--    Fixed: table renamed to guild_configs with the correct columns.
--
-- 3. streamers had no twitch_login column — streamer_queries.py upserts
--    twitch_login and guild_id into the table, causing a column-not-found
--    error on every upsert.
--
-- 4. streamers had no discord_user_id column — live_role_cog.py uses it
--    for direct member matching (more reliable than nickname scanning).
--
-- 5. last_game column was named last_game but streamer_queries.py and
--    stream_events.py always use game_name — renamed for consistency.
--
-- 6. streamer_states table referenced in live_notifier.py didn't exist.
--
-- 7. guild_notification_channels table referenced in channel_registry.py
--    didn't exist.
--
-- 8. All TIMESTAMP columns changed to TIMESTAMPTZ (timezone-aware).
--    Storing bare timestamps in a multi-region app causes ambiguous
--    timezone bugs when comparing against Python's datetime.now(timezone.utc).
--
-- 9. twitch_event_logs had no index on broadcaster_id or created_at —
--    any lookup or TTL-based cleanup would do a full table scan.
--
-- 10. No schema_migrations table — no way to know which migrations have run.
-- =============================================================================

BEGIN;

-- =============================================================================
-- EXTENSIONS
-- =============================================================================

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";   -- enables fast ILIKE / trigram search


-- =============================================================================
-- MIGRATION TRACKING
-- =============================================================================
-- Run this before any other table so the migration runner can record itself.

CREATE TABLE IF NOT EXISTS schema_migrations (
    version     TEXT        PRIMARY KEY,
    applied_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);


-- =============================================================================
-- STREAMERS
-- =============================================================================
-- One row per tracked Twitch broadcaster.
-- Guild-level notification settings live in guild_configs, not here.

CREATE TABLE IF NOT EXISTS streamers (

    -- Identity
    broadcaster_id  TEXT    NOT NULL PRIMARY KEY,
    twitch_login    TEXT    NOT NULL,

    -- Optional link to a Discord member (used by live_role_cog for direct match)
    discord_user_id BIGINT,

    -- Which guild "owns" this streamer record (for multi-guild setups)
    guild_id        BIGINT,

    -- Live state (kept in sync by monitor.py + EventSub)
    is_live         BOOLEAN     NOT NULL DEFAULT FALSE,
    title           TEXT,
    game_name       TEXT,        -- matches Twitch API field name exactly
    viewer_count    INTEGER,

    -- Timestamps
    last_updated    TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Fast lookup by login (used in event_router, stream_events)
CREATE INDEX IF NOT EXISTS idx_streamers_login
    ON streamers (twitch_login);

-- Partial index — only live streamers (monitor.py queries this constantly)
CREATE INDEX IF NOT EXISTS idx_streamers_live
    ON streamers (is_live)
    WHERE is_live = TRUE;


-- =============================================================================
-- STREAMER STATES
-- =============================================================================
-- Per-streamer live state history used by live_notifier.py polling loop.
-- Separate from streamers so the main table stays clean.

CREATE TABLE IF NOT EXISTS streamer_states (

    twitch_user_id  TEXT        NOT NULL PRIMARY KEY,
    is_live         BOOLEAN     NOT NULL DEFAULT FALSE,
    title           TEXT,
    game_name       TEXT,
    viewer_count    INTEGER,
    last_updated    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);


-- =============================================================================
-- GUILD CONFIGS
-- =============================================================================
-- One row per Discord guild. All guild-level notification settings live here.
-- This is the table queried by guild_settings.get_guild_config().

CREATE TABLE IF NOT EXISTS guild_configs (

    guild_id            BIGINT  NOT NULL PRIMARY KEY,

    -- Channel where stream live/offline notifications are posted
    announce_channel_id BIGINT,

    -- Channel where free games / deals / Luna posts are sent
    -- Falls back to announce_channel_id if NULL (see guild_settings.py)
    games_channel_id    BIGINT,

    -- Role pinged when a stream goes live
    ping_role_id        BIGINT,

    -- Role assigned to members while they are streaming (live_role_cog)
    live_role_id        BIGINT,

    -- Toggles
    notify_enabled  BOOLEAN NOT NULL DEFAULT TRUE,
    enable_ping     BOOLEAN NOT NULL DEFAULT TRUE,
    enable_epic     BOOLEAN NOT NULL DEFAULT FALSE,
    enable_gog      BOOLEAN NOT NULL DEFAULT FALSE,
    enable_steam    BOOLEAN NOT NULL DEFAULT FALSE,

    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);


-- =============================================================================
-- GUILD SETTINGS  (legacy — kept for backward-compat fallback in guild_settings.py)
-- =============================================================================
-- guild_settings.py falls back to this table for guilds not yet in guild_configs.
-- New guilds should go straight into guild_configs.

CREATE TABLE IF NOT EXISTS guild_settings (

    guild_id            BIGINT  NOT NULL PRIMARY KEY,
    announce_channel_id BIGINT,
    games_channel_id    BIGINT,

    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);


-- =============================================================================
-- GUILD NOTIFICATION CHANNELS
-- =============================================================================
-- Flat channel list loaded by channel_registry.load_channels().
-- Allows a guild to have multiple notification channels if needed.

CREATE TABLE IF NOT EXISTS guild_notification_channels (

    id          BIGSERIAL   PRIMARY KEY,
    guild_id    BIGINT      NOT NULL,
    channel_id  BIGINT      NOT NULL,
    is_active   BOOLEAN     NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE (guild_id, channel_id)
);

CREATE INDEX IF NOT EXISTS idx_notif_channels_guild
    ON guild_notification_channels (guild_id)
    WHERE is_active = TRUE;


-- =============================================================================
-- TWITCH EVENT LOGS
-- =============================================================================
-- Append-only audit log of every raw EventSub event received.
-- Useful for debugging missed notifications and replaying events.

CREATE TABLE IF NOT EXISTS twitch_event_logs (

    id              UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    event_type      TEXT        NOT NULL,
    broadcaster_id  TEXT,
    payload         JSONB       NOT NULL DEFAULT '{}',
    received_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Fast lookups by broadcaster and time range
CREATE INDEX IF NOT EXISTS idx_event_logs_broadcaster
    ON twitch_event_logs (broadcaster_id, received_at DESC);

CREATE INDEX IF NOT EXISTS idx_event_logs_received
    ON twitch_event_logs (received_at DESC);

-- GIN index for querying inside the JSONB payload
CREATE INDEX IF NOT EXISTS idx_event_logs_payload
    ON twitch_event_logs USING GIN (payload);


-- =============================================================================
-- UPDATED_AT TRIGGER
-- =============================================================================
-- Automatically keeps updated_at current on guild_configs.

CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_guild_configs_updated_at ON guild_configs;
CREATE TRIGGER trg_guild_configs_updated_at
    BEFORE UPDATE ON guild_configs
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();


-- =============================================================================
-- RECORD THIS MIGRATION
-- =============================================================================

INSERT INTO schema_migrations (version) VALUES ('001_init')
    ON CONFLICT (version) DO NOTHING;

COMMIT;
