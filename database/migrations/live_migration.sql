-- =============================================================================
-- live_migration.sql  —  RUN ONCE
-- Railway → Postgres service → Query tab → Paste → Run
--
-- What this does:
--   1. Renames guild_configs."channel_id" → "announce_channel_id"
--      (old code wrote channel_id; new code expects announce_channel_id)
--   2. Adds missing columns (games_channel_id, notify_enabled, enable_ping …)
--   3. Inserts the KevKevvy's Plaza channel config — 1446562626695074006
--   4. Creates any other missing tables
--   5. Does NOT touch existing streamers data
-- =============================================================================

BEGIN;

-- ── 1. Create guild_configs if it doesn't exist yet ──────────────────────────
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

-- ── 2. Rename "channel_id" → "announce_channel_id" if the old name still exists
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'guild_configs' AND column_name = 'channel_id'
    ) AND NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'guild_configs' AND column_name = 'announce_channel_id'
    ) THEN
        ALTER TABLE guild_configs RENAME COLUMN channel_id TO announce_channel_id;
        RAISE NOTICE 'Renamed channel_id → announce_channel_id';
    ELSE
        RAISE NOTICE 'Column already has correct name or rename not needed';
    END IF;
END;
$$;

-- ── 3. Add missing columns (IF NOT EXISTS — safe if already present) ─────────
ALTER TABLE guild_configs ADD COLUMN IF NOT EXISTS announce_channel_id BIGINT;
ALTER TABLE guild_configs ADD COLUMN IF NOT EXISTS games_channel_id    BIGINT;
ALTER TABLE guild_configs ADD COLUMN IF NOT EXISTS ping_role_id        BIGINT;
ALTER TABLE guild_configs ADD COLUMN IF NOT EXISTS live_role_id        BIGINT;
ALTER TABLE guild_configs ADD COLUMN IF NOT EXISTS notify_enabled      BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE guild_configs ADD COLUMN IF NOT EXISTS enable_ping         BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE guild_configs ADD COLUMN IF NOT EXISTS enable_epic         BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE guild_configs ADD COLUMN IF NOT EXISTS enable_gog          BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE guild_configs ADD COLUMN IF NOT EXISTS enable_steam        BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE guild_configs ADD COLUMN IF NOT EXISTS created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW();
ALTER TABLE guild_configs ADD COLUMN IF NOT EXISTS updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW();

-- ── 4. Auto-update updated_at on every guild_configs row change ───────────────
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

-- ── 5. guild_settings (legacy — /live set-channel writes here for compatibility)
CREATE TABLE IF NOT EXISTS guild_settings (
    guild_id            BIGINT NOT NULL PRIMARY KEY,
    announce_channel_id BIGINT,
    games_channel_id    BIGINT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ── 6. guild_notification_channels ───────────────────────────────────────────
CREATE TABLE IF NOT EXISTS guild_notification_channels (
    id          BIGSERIAL   PRIMARY KEY,
    guild_id    BIGINT      NOT NULL,
    channel_id  BIGINT      NOT NULL,
    is_active   BOOLEAN     NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (guild_id, channel_id)
);

-- ── 7. streamer_states ────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS streamer_states (
    twitch_user_id  TEXT        NOT NULL PRIMARY KEY,
    is_live         BOOLEAN     NOT NULL DEFAULT FALSE,
    title           TEXT,
    game_name       TEXT,
    viewer_count    INTEGER,
    last_updated    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ── 8. Add missing columns to streamers ──────────────────────────────────────
ALTER TABLE streamers ADD COLUMN IF NOT EXISTS is_live          BOOLEAN     NOT NULL DEFAULT FALSE;
ALTER TABLE streamers ADD COLUMN IF NOT EXISTS title            TEXT;
ALTER TABLE streamers ADD COLUMN IF NOT EXISTS game_name        TEXT;
ALTER TABLE streamers ADD COLUMN IF NOT EXISTS viewer_count     INTEGER;
ALTER TABLE streamers ADD COLUMN IF NOT EXISTS last_updated     TIMESTAMPTZ;
ALTER TABLE streamers ADD COLUMN IF NOT EXISTS target_channel_id BIGINT;
ALTER TABLE streamers ADD COLUMN IF NOT EXISTS discord_user_id  BIGINT;

-- Ensure UNIQUE constraint exists on twitch_user_id for ON CONFLICT upserts
CREATE UNIQUE INDEX IF NOT EXISTS idx_streamers_twitch_user_id
    ON streamers (twitch_user_id);

-- ── 9. stream_history — per-stream session log ────────────────────────────────
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

-- ── 10. user_notifications — per-user DM opt-in subscriptions ─────────────────
CREATE TABLE IF NOT EXISTS user_notifications (
    user_id      BIGINT  NOT NULL,
    guild_id     BIGINT  NOT NULL,
    twitch_login TEXT    NOT NULL,
    PRIMARY KEY (user_id, twitch_login)
);

-- ── 11. Write KevKevvy's Plaza config ────────────────────────────────────────
--        Guild:          1446560723122520207
--        Stream channel: 1446562626695074006
--        Games channel:  1450903610559823873
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
    notify_enabled      = EXCLUDED.notify_enabled,
    updated_at          = NOW();

-- Keep guild_settings in sync (/live set-channel reads from here too)
INSERT INTO guild_settings (guild_id, announce_channel_id, games_channel_id)
VALUES (1446560723122520207, 1446562626695074006, 1450903610559823873)
ON CONFLICT (guild_id) DO UPDATE SET
    announce_channel_id = EXCLUDED.announce_channel_id,
    games_channel_id    = EXCLUDED.games_channel_id;

-- ── 12. Migration tracking ────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS schema_migrations (
    version     TEXT        PRIMARY KEY,
    applied_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO schema_migrations (version) VALUES ('live_migration_2026_03_28')
    ON CONFLICT (version) DO NOTHING;

COMMIT;

-- Verify: these should show correct values
SELECT guild_id, announce_channel_id, games_channel_id, notify_enabled
FROM guild_configs
WHERE guild_id = 1446560723122520207;
