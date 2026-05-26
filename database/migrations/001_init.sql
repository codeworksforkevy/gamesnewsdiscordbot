-- =============================================================================
-- 001_init.sql
-- Initial schema — run once on a fresh database.
-- =============================================================================
-- FIXES vs original:
--
-- 1. streamers.broadcaster_id renamed to twitch_user_id to match the actual
--    live database column name and all Python queries (streamer_queries.py,
--    live_commands.py, migrations.py all use twitch_user_id).
--
-- 2. guild_config (singular) renamed to guild_configs (plural) with the full
--    column set that guild_settings.get_guild_config() actually reads.
--
-- 3. streamers was missing twitch_login, discord_user_id, is_live, title,
--    game_name, viewer_count, last_updated — streamer_queries.py writes all
--    of them. Added.
--
-- 4. discord_user_id added to streamers — live_role_cog uses it for reliable
--    member matching without nickname scanning.
--
-- 5. stream_history and user_notifications tables added — live_commands.py
--    writes stream sessions and DM subscriptions to these tables.
--
-- 6. All TIMESTAMP → TIMESTAMPTZ (timezone-aware).
--
-- 7. enable_epic / enable_gog / enable_steam default changed TRUE → FALSE
--    (opt-in rather than opt-out).
--
-- 8. Missing NOT NULL on boolean flags.
--
-- 9. Indexes added on twitch_user_id, twitch_login, and is_live.
--
-- 10. schema_migrations table added for migration tracking.
-- =============================================================================

BEGIN;

-- =============================================================================
-- EXTENSIONS
-- =============================================================================

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";

-- =============================================================================
-- MIGRATION TRACKING
-- =============================================================================

CREATE TABLE IF NOT EXISTS schema_migrations (
    version     TEXT        PRIMARY KEY,
    applied_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- =============================================================================
-- SHARED TRIGGER FUNCTION
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
-- One row per Discord guild. Single source of truth for per-guild settings.
-- Read by guild_settings.get_guild_config().

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

-- =============================================================================
-- GUILD SETTINGS  (legacy fallback)
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
-- STREAMERS
-- =============================================================================
-- One row per tracked Twitch broadcaster.
-- Column is twitch_user_id (matches Twitch API field and all Python queries).

CREATE TABLE IF NOT EXISTS streamers (
    id              BIGSERIAL   PRIMARY KEY,
    twitch_user_id  TEXT        NOT NULL,
    twitch_login    TEXT        NOT NULL,
    discord_user_id BIGINT,
    guild_id        BIGINT,
    is_live         BOOLEAN     NOT NULL DEFAULT FALSE,
    title           TEXT,
    game_name       TEXT,
    viewer_count    INTEGER,
    last_updated    TIMESTAMPTZ,
    target_channel_id BIGINT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (twitch_user_id)
);

CREATE INDEX IF NOT EXISTS idx_streamers_login
    ON streamers (twitch_login);

CREATE INDEX IF NOT EXISTS idx_streamers_live
    ON streamers (is_live)
    WHERE is_live = TRUE;

CREATE INDEX IF NOT EXISTS idx_streamers_guild
    ON streamers (guild_id);

-- =============================================================================
-- STREAMER STATES
-- =============================================================================

CREATE TABLE IF NOT EXISTS streamer_states (
    twitch_user_id  TEXT        NOT NULL PRIMARY KEY,
    is_live         BOOLEAN     NOT NULL DEFAULT FALSE,
    title           TEXT,
    game_name       TEXT,
    viewer_count    INTEGER,
    last_updated    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_streamer_states_live
    ON streamer_states (is_live)
    WHERE is_live = TRUE;

-- =============================================================================
-- STREAM HISTORY
-- =============================================================================
-- One row per stream session. Written by live_commands._post_live() and
-- updated with duration when the stream ends in _post_offline().

CREATE TABLE IF NOT EXISTS stream_history (
    id            BIGSERIAL   PRIMARY KEY,
    twitch_login  TEXT        NOT NULL,
    guild_id      BIGINT      NOT NULL,
    title         TEXT,
    game_name     TEXT,
    peak_viewers  INTEGER     DEFAULT 0,
    started_at    TIMESTAMPTZ,
    ended_at      TIMESTAMPTZ,
    duration_secs INTEGER     DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_stream_history_login
    ON stream_history (twitch_login, started_at DESC);

-- =============================================================================
-- USER NOTIFICATIONS
-- =============================================================================
-- Per-user DM opt-in subscriptions managed by /notify commands.

CREATE TABLE IF NOT EXISTS user_notifications (
    user_id      BIGINT  NOT NULL,
    guild_id     BIGINT  NOT NULL,
    twitch_login TEXT    NOT NULL,
    PRIMARY KEY (user_id, twitch_login)
);

-- =============================================================================
-- TWITCH EVENT LOGS
-- =============================================================================

CREATE TABLE IF NOT EXISTS twitch_event_logs (
    id              UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    event_type      TEXT        NOT NULL DEFAULT 'unknown',
    broadcaster_id  TEXT,
    payload         JSONB       NOT NULL DEFAULT '{}',
    received_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_event_logs_broadcaster
    ON twitch_event_logs (broadcaster_id, received_at DESC);

CREATE INDEX IF NOT EXISTS idx_event_logs_received
    ON twitch_event_logs (received_at DESC);

CREATE INDEX IF NOT EXISTS idx_event_logs_payload
    ON twitch_event_logs USING GIN (payload);

-- =============================================================================
-- RECORD MIGRATION
-- =============================================================================

INSERT INTO schema_migrations (version) VALUES ('001_init')
    ON CONFLICT (version) DO NOTHING;

COMMIT;
