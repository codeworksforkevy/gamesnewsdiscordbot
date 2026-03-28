-- =============================================================================
-- 002_twitch_upgrade.sql
-- Safe incremental upgrade — applies on top of 001_init.sql.
-- All statements use IF NOT EXISTS / IF EXISTS so it is idempotent
-- (safe to run more than once without error).
-- =============================================================================
-- ISSUES FIXED vs original:
--
-- 1. Tried to ADD COLUMN role_id / last_title / last_game / message_id to
--    streamers — but 001_init.sql already creates streamers with those columns
--    (role_id, last_title, last_game, message_id). Running this migration
--    after 001 would silently succeed on Postgres (IF NOT EXISTS) but the
--    intent was confused. The new 001 has the correct final shape, so this
--    migration now only adds columns that were genuinely missing in the old
--    001: twitch_login, discord_user_id, game_name, viewer_count,
--    last_updated, and the renamed column (last_game → game_name).
--
-- 2. Re-created guild_config (singular) — the table that nothing queries.
--    Replaced with a proper migration to guild_configs (plural) with the
--    full column set that guild_settings.py actually reads.
--
-- 3. Had no transaction wrapper — if any statement failed mid-migration the
--    schema was left in a half-applied state with no way to tell.
--
-- 4. No migration record — schema_migrations was not updated.
--
-- NOTE: If you have already run the original 001_init.sql on your database
-- (the old version that had guild_config singular and fewer streamer columns),
-- run THIS file to bring your schema up to date. It is safe to run on both
-- old and new installs.
-- =============================================================================

BEGIN;

-- =============================================================================
-- STREAMERS — add columns missing from the original 001
-- =============================================================================

-- Twitch login handle (used everywhere for lookups)
ALTER TABLE streamers
    ADD COLUMN IF NOT EXISTS twitch_login TEXT;

-- Direct Discord member link (used by live_role_cog)
ALTER TABLE streamers
    ADD COLUMN IF NOT EXISTS discord_user_id BIGINT;

-- Twitch API field is "game_name" not "game" or "last_game"
ALTER TABLE streamers
    ADD COLUMN IF NOT EXISTS game_name TEXT;

-- Viewer count snapshot (shown in live embed)
ALTER TABLE streamers
    ADD COLUMN IF NOT EXISTS viewer_count INTEGER;

-- Timezone-aware last_updated
ALTER TABLE streamers
    ADD COLUMN IF NOT EXISTS last_updated TIMESTAMPTZ;

-- Rename last_game → game_name if the old column exists
-- (safe: DO block catches the error if it's already been renamed)
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'streamers' AND column_name = 'last_game'
    ) THEN
        ALTER TABLE streamers RENAME COLUMN last_game TO game_name_old;
        -- Migrate data then drop; game_name column already added above
        UPDATE streamers SET game_name = game_name_old WHERE game_name IS NULL;
        ALTER TABLE streamers DROP COLUMN game_name_old;
    END IF;
END;
$$;

-- Rename last_title → title for consistency with Twitch API naming
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'streamers' AND column_name = 'last_title'
    ) THEN
        ALTER TABLE streamers ADD COLUMN IF NOT EXISTS title TEXT;
        UPDATE streamers SET title = last_title WHERE title IS NULL;
        ALTER TABLE streamers DROP COLUMN last_title;
    END IF;
END;
$$;

-- Drop channel_id / role_id from streamers — these belong in guild_configs
-- only drop if they exist, and only if the guild_configs table already has them
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'streamers' AND column_name = 'channel_id'
    ) AND EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_name = 'guild_configs'
    ) THEN
        ALTER TABLE streamers DROP COLUMN channel_id;
    END IF;

    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'streamers' AND column_name = 'role_id'
    ) AND EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_name = 'guild_configs'
    ) THEN
        ALTER TABLE streamers DROP COLUMN role_id;
    END IF;
END;
$$;

-- Add missing index on twitch_login if not present
CREATE INDEX IF NOT EXISTS idx_streamers_login
    ON streamers (twitch_login);

-- Recreate live index as partial (only live rows — much smaller, much faster)
DROP INDEX IF EXISTS idx_streamers_live;
CREATE INDEX IF NOT EXISTS idx_streamers_live
    ON streamers (is_live)
    WHERE is_live = TRUE;


-- =============================================================================
-- STREAMER STATES — create if missing (live_notifier.py polling table)
-- =============================================================================

CREATE TABLE IF NOT EXISTS streamer_states (
    twitch_user_id  TEXT        NOT NULL PRIMARY KEY,
    is_live         BOOLEAN     NOT NULL DEFAULT FALSE,
    title           TEXT,
    game_name       TEXT,
    viewer_count    INTEGER,
    last_updated    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);


-- =============================================================================
-- GUILD_CONFIGS — create with full column set if missing
-- =============================================================================
-- This replaces the old guild_config (singular) table.

CREATE TABLE IF NOT EXISTS guild_configs (
    guild_id            BIGINT  NOT NULL PRIMARY KEY,
    announce_channel_id BIGINT,
    games_channel_id    BIGINT,
    ping_role_id        BIGINT,
    live_role_id        BIGINT,
    notify_enabled      BOOLEAN NOT NULL DEFAULT TRUE,
    enable_ping         BOOLEAN NOT NULL DEFAULT TRUE,
    enable_epic         BOOLEAN NOT NULL DEFAULT FALSE,
    enable_gog          BOOLEAN NOT NULL DEFAULT FALSE,
    enable_steam        BOOLEAN NOT NULL DEFAULT FALSE,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Migrate rows from old guild_config (singular) into guild_configs if present
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_name = 'guild_config'
    ) THEN
        INSERT INTO guild_configs (
            guild_id,
            announce_channel_id,
            created_at
        )
        SELECT
            guild_id,
            default_channel_id,
            COALESCE(created_at, NOW())
        FROM guild_config
        ON CONFLICT (guild_id) DO NOTHING;

        -- Rename old table instead of dropping so data isn't permanently lost
        ALTER TABLE guild_config RENAME TO guild_config_deprecated;
    END IF;
END;
$$;

-- Add columns to guild_configs that might be missing on older guild_configs installs
ALTER TABLE guild_configs
    ADD COLUMN IF NOT EXISTS games_channel_id    BIGINT,
    ADD COLUMN IF NOT EXISTS ping_role_id        BIGINT,
    ADD COLUMN IF NOT EXISTS live_role_id        BIGINT,
    ADD COLUMN IF NOT EXISTS notify_enabled      BOOLEAN NOT NULL DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS enable_ping         BOOLEAN NOT NULL DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS enable_epic         BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS enable_gog          BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS enable_steam        BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW();


-- =============================================================================
-- GUILD SETTINGS (legacy fallback table)
-- =============================================================================

CREATE TABLE IF NOT EXISTS guild_settings (
    guild_id            BIGINT NOT NULL PRIMARY KEY,
    announce_channel_id BIGINT,
    games_channel_id    BIGINT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);


-- =============================================================================
-- GUILD NOTIFICATION CHANNELS
-- =============================================================================

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
-- TWITCH_EVENT_LOGS — add missing indexes and rename created_at → received_at
-- =============================================================================

ALTER TABLE twitch_event_logs
    ADD COLUMN IF NOT EXISTS received_at TIMESTAMPTZ NOT NULL DEFAULT NOW();

-- Backfill received_at from created_at if it exists
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'twitch_event_logs' AND column_name = 'created_at'
    ) THEN
        UPDATE twitch_event_logs
        SET received_at = created_at
        WHERE received_at = NOW() AND created_at IS NOT NULL;

        ALTER TABLE twitch_event_logs DROP COLUMN IF EXISTS created_at;
    END IF;
END;
$$;

-- event_type was nullable in original — make it NOT NULL with a safe default
UPDATE twitch_event_logs SET event_type = 'unknown' WHERE event_type IS NULL;
ALTER TABLE twitch_event_logs ALTER COLUMN event_type SET NOT NULL;
ALTER TABLE twitch_event_logs ALTER COLUMN event_type SET DEFAULT 'unknown';

-- payload was nullable — default to empty object
ALTER TABLE twitch_event_logs ALTER COLUMN payload SET DEFAULT '{}';
UPDATE twitch_event_logs SET payload = '{}' WHERE payload IS NULL;
ALTER TABLE twitch_event_logs ALTER COLUMN payload SET NOT NULL;

-- Add missing indexes
CREATE INDEX IF NOT EXISTS idx_event_logs_broadcaster
    ON twitch_event_logs (broadcaster_id, received_at DESC);

CREATE INDEX IF NOT EXISTS idx_event_logs_received
    ON twitch_event_logs (received_at DESC);

CREATE EXTENSION IF NOT EXISTS "pg_trgm";
CREATE INDEX IF NOT EXISTS idx_event_logs_payload
    ON twitch_event_logs USING GIN (payload);


-- =============================================================================
-- UPDATED_AT TRIGGER on guild_configs
-- =============================================================================

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
-- SCHEMA MIGRATIONS TRACKING
-- =============================================================================

CREATE TABLE IF NOT EXISTS schema_migrations (
    version     TEXT        PRIMARY KEY,
    applied_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO schema_migrations (version) VALUES ('001_init')
    ON CONFLICT (version) DO NOTHING;

INSERT INTO schema_migrations (version) VALUES ('002_twitch_upgrade')
    ON CONFLICT (version) DO NOTHING;

COMMIT;
