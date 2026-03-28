-- =============================================================================
-- database/schema.sql
-- Master schema — creates ALL tables in correct dependency order.
-- Run this on a fresh database. For existing databases use the migrations.
--
-- Individual table files (guild_configs.sql, streamers.sql, etc.) are the
-- authoritative definitions. This file composes them into a single runnable
-- script so you can spin up a clean dev/test database in one command:
--
--     psql $DATABASE_URL -f database/schema.sql
-- =============================================================================
-- FIXES vs original:
--
-- 1. schema.sql defined guild_configs and streamer_states in-line but used
--    different column sets than the standalone .sql files, creating three
--    divergent definitions of the same tables. Any table created from
--    schema.sql would be missing columns that the Python code expected.
--    Fixed: schema.sql is now the composition point — it defines every
--    table once, with the full correct column set.
--
-- 2. streamers in schema.sql used (guild_id, twitch_user_id) as a UNIQUE
--    composite key with a SERIAL surrogate PK — but streamer_queries.py
--    does ON CONFLICT (broadcaster_id) DO UPDATE. A composite unique key
--    on (guild_id, twitch_user_id) is NOT the same conflict target, so
--    every upsert would insert a duplicate row instead of updating.
--    Fixed: broadcaster_id TEXT PRIMARY KEY (matching all Python queries).
--
-- 3. All TIMESTAMP → TIMESTAMPTZ (timezone-aware).
--
-- 4. Missing tables that other files reference:
--    - guild_notification_channels (channel_registry.py)
--    - guild_settings              (guild_settings.py legacy fallback)
--    - twitch_event_logs           (debugging / audit)
--    - schema_migrations           (migration tracking)
--    All added.
--
-- 5. enable_epic/gog/steam defaulted TRUE → changed to FALSE (opt-in).
--
-- 6. Missing NOT NULL on boolean flags (notify_enabled, enable_ping, etc.).
-- =============================================================================

BEGIN;

-- =============================================================================
-- EXTENSIONS
-- =============================================================================

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";   -- uuid_generate_v4()
CREATE EXTENSION IF NOT EXISTS "pg_trgm";     -- fast ILIKE / trigram search

-- =============================================================================
-- MIGRATION TRACKING
-- =============================================================================

CREATE TABLE IF NOT EXISTS schema_migrations (
    version     TEXT        PRIMARY KEY,
    applied_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- =============================================================================
-- SHARED TRIGGER FUNCTION: updated_at
-- =============================================================================

CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;

-- =============================================================================
-- GUILD CONFIGS
-- =============================================================================
-- One row per Discord guild. Single source of truth for all per-guild settings.
-- Read by guild_settings.get_guild_config().

CREATE TABLE IF NOT EXISTS guild_configs (

    guild_id BIGINT PRIMARY KEY,

    -- Stream live/offline notification channel
    announce_channel_id BIGINT,

    -- Free games / deals channel
    -- NULL → falls back to announce_channel_id (see guild_settings.py)
    games_channel_id    BIGINT,

    -- Role pinged when a stream goes live
    ping_role_id        BIGINT,

    -- Role assigned to members while they are streaming (live_role_cog)
    live_role_id        BIGINT,

    -- Master notification switch
    notify_enabled  BOOLEAN NOT NULL DEFAULT TRUE,

    -- Ping role on live notifications
    enable_ping     BOOLEAN NOT NULL DEFAULT TRUE,

    -- Game deal notifications (opt-in, not opt-out)
    enable_epic     BOOLEAN NOT NULL DEFAULT FALSE,
    enable_gog      BOOLEAN NOT NULL DEFAULT FALSE,
    enable_steam    BOOLEAN NOT NULL DEFAULT FALSE,

    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

DROP TRIGGER IF EXISTS trg_guild_configs_updated_at ON guild_configs;
CREATE TRIGGER trg_guild_configs_updated_at
    BEFORE UPDATE ON guild_configs
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- =============================================================================
-- GUILD SETTINGS  (legacy fallback)
-- =============================================================================
-- Queried by guild_settings.py when a guild is not in guild_configs yet.
-- New guilds should go directly into guild_configs.

CREATE TABLE IF NOT EXISTS guild_settings (
    guild_id            BIGINT NOT NULL PRIMARY KEY,
    announce_channel_id BIGINT,
    games_channel_id    BIGINT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- =============================================================================
-- GUILD NOTIFICATION CHANNELS
-- =============================================================================
-- Flat list loaded by channel_registry.load_channels() at startup.
-- Allows a guild to register multiple notification channels.

CREATE TABLE IF NOT EXISTS guild_notification_channels (
    id          BIGSERIAL   PRIMARY KEY,
    guild_id    BIGINT      NOT NULL,
    channel_id  BIGINT      NOT NULL,
    is_active   BOOLEAN     NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE (guild_id, channel_id)
);

CREATE INDEX IF NOT EXISTS idx_notif_channels_active
    ON guild_notification_channels (guild_id)
    WHERE is_active = TRUE;

-- =============================================================================
-- STREAMERS
-- =============================================================================
-- One row per tracked Twitch broadcaster (global, not per-guild).
-- Notifications fan out to all guilds via guild_configs at dispatch time.

CREATE TABLE IF NOT EXISTS streamers (

    broadcaster_id  TEXT    NOT NULL PRIMARY KEY,   -- Twitch numeric user ID
    twitch_login    TEXT    NOT NULL,               -- lowercased handle, e.g. "ninja"

    -- Optional Discord member link for reliable role assignment
    -- (live_role_cog uses this; falls back to nickname scan if NULL)
    discord_user_id BIGINT,

    -- Which guild added this broadcaster (informational)
    guild_id        BIGINT,

    -- Live state — kept in sync by EventSub + monitor.py reconciliation
    is_live         BOOLEAN     NOT NULL DEFAULT FALSE,
    title           TEXT,
    game_name       TEXT,
    viewer_count    INTEGER,
    last_updated    TIMESTAMPTZ,

    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Login lookups (event payloads arrive as login string)
CREATE INDEX IF NOT EXISTS idx_streamers_login
    ON streamers (twitch_login);

-- Partial index — monitor.py queries live streamers every cycle
CREATE INDEX IF NOT EXISTS idx_streamers_live
    ON streamers (is_live)
    WHERE is_live = TRUE;

-- Guild lookups (admin commands, per-guild lists)
CREATE INDEX IF NOT EXISTS idx_streamers_guild
    ON streamers (guild_id);

-- =============================================================================
-- STREAMER STATES
-- =============================================================================
-- Per-broadcaster live state snapshot used by the live_notifier.py polling
-- loop to detect online/offline transitions between poll cycles.

CREATE TABLE IF NOT EXISTS streamer_states (

    twitch_user_id  TEXT        NOT NULL PRIMARY KEY,
    is_live         BOOLEAN     NOT NULL DEFAULT FALSE,
    title           TEXT,
    game_name       TEXT,
    viewer_count    INTEGER,
    last_updated    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE OR REPLACE FUNCTION set_streamer_states_updated()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    NEW.last_updated = NOW();
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_streamer_states_updated ON streamer_states;
CREATE TRIGGER trg_streamer_states_updated
    BEFORE INSERT OR UPDATE ON streamer_states
    FOR EACH ROW EXECUTE FUNCTION set_streamer_states_updated();

-- Partial index — reconciliation only touches live rows
CREATE INDEX IF NOT EXISTS idx_streamer_states_live
    ON streamer_states (is_live)
    WHERE is_live = TRUE;

-- =============================================================================
-- TWITCH EVENT LOGS
-- =============================================================================
-- Append-only audit log of every raw EventSub notification received.
-- Useful for debugging missed events and replaying them.

CREATE TABLE IF NOT EXISTS twitch_event_logs (

    id              UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    event_type      TEXT        NOT NULL DEFAULT 'unknown',
    broadcaster_id  TEXT,
    payload         JSONB       NOT NULL DEFAULT '{}',
    received_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Broadcaster + time range lookups
CREATE INDEX IF NOT EXISTS idx_event_logs_broadcaster
    ON twitch_event_logs (broadcaster_id, received_at DESC);

-- Recent events (admin debug view)
CREATE INDEX IF NOT EXISTS idx_event_logs_received
    ON twitch_event_logs (received_at DESC);

-- Query inside JSONB payloads
CREATE INDEX IF NOT EXISTS idx_event_logs_payload
    ON twitch_event_logs USING GIN (payload);

-- =============================================================================
-- RECORD MIGRATION
-- =============================================================================

INSERT INTO schema_migrations (version) VALUES ('schema_initial')
    ON CONFLICT (version) DO NOTHING;

COMMIT;
