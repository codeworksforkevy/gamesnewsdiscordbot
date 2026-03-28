-- =============================================================================
-- live_migration.sql
-- Run this ONCE in Railway → Postgres service → Query tab.
--
-- Your announce channel 1446562626695074006 was already saved by /live set-channel
-- into guild_settings. This script:
--   1. Creates all missing tables (IF NOT EXISTS — safe, touches nothing existing)
--   2. Copies your existing guild_settings row into guild_configs so the bot
--      finds it (guild_settings.py reads guild_configs first)
--   3. Does NOT touch your streamers rows
-- =============================================================================

BEGIN;

-- ── Extensions ────────────────────────────────────────────────────────────────
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";

-- ── Migration tracking ────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS schema_migrations (
    version     TEXT        PRIMARY KEY,
    applied_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ── updated_at trigger ────────────────────────────────────────────────────────
CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;

-- ── guild_configs (the table the bot actually reads) ──────────────────────────
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

DROP TRIGGER IF EXISTS trg_guild_configs_updated_at ON guild_configs;
CREATE TRIGGER trg_guild_configs_updated_at
    BEFORE UPDATE ON guild_configs
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ── guild_settings (legacy — keep it, /live set-channel still writes here) ────
CREATE TABLE IF NOT EXISTS guild_settings (
    guild_id            BIGINT NOT NULL PRIMARY KEY,
    announce_channel_id BIGINT,
    games_channel_id    BIGINT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ── guild_notification_channels ───────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS guild_notification_channels (
    id          BIGSERIAL   PRIMARY KEY,
    guild_id    BIGINT      NOT NULL,
    channel_id  BIGINT      NOT NULL,
    is_active   BOOLEAN     NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (guild_id, channel_id)
);

-- ── streamer_states ───────────────────────────────────────────────────────────
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

-- ── Missing columns on streamers ──────────────────────────────────────────────
ALTER TABLE streamers ADD COLUMN IF NOT EXISTS is_live      BOOLEAN     NOT NULL DEFAULT FALSE;
ALTER TABLE streamers ADD COLUMN IF NOT EXISTS title        TEXT;
ALTER TABLE streamers ADD COLUMN IF NOT EXISTS game_name    TEXT;
ALTER TABLE streamers ADD COLUMN IF NOT EXISTS viewer_count INTEGER;
ALTER TABLE streamers ADD COLUMN IF NOT EXISTS last_updated TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_streamers_login ON streamers (twitch_login);
CREATE INDEX IF NOT EXISTS idx_streamers_live  ON streamers (is_live) WHERE is_live = TRUE;
CREATE INDEX IF NOT EXISTS idx_streamers_guild ON streamers (guild_id);

-- =============================================================================
-- COPY YOUR CHANNEL CONFIG INTO guild_configs
-- Guild:   KevKevvy's Plaza  (1446560723122520207)
-- Channel: 1446562626695074006
-- =============================================================================

INSERT INTO guild_configs (
    guild_id,
    announce_channel_id,
    games_channel_id,
    notify_enabled,
    enable_ping
)
VALUES (
    1446560723122520207,
    1446562626695074006,
    1450903610559823873,
    TRUE,
    FALSE
)
ON CONFLICT (guild_id) DO UPDATE SET
    announce_channel_id = EXCLUDED.announce_channel_id,
    games_channel_id    = EXCLUDED.games_channel_id,
    updated_at          = NOW();

-- Keep guild_settings in sync so /live set-channel keeps working
INSERT INTO guild_settings (guild_id, announce_channel_id)
VALUES (1446560723122520207, 1446562626695074006)
ON CONFLICT (guild_id) DO UPDATE SET
    announce_channel_id = EXCLUDED.announce_channel_id;

-- ── Record ────────────────────────────────────────────────────────────────────
INSERT INTO schema_migrations (version) VALUES ('live_migration_2026_03_28')
    ON CONFLICT (version) DO NOTHING;

COMMIT;
