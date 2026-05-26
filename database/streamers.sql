-- =============================================================================
-- database/streamers.sql
-- One row per tracked Twitch broadcaster.
-- Guild-level settings (channel, roles) live in guild_configs — not here.
-- =============================================================================
-- FIXES vs original:
--
-- 1. Primary key renamed broadcaster_id → twitch_user_id to match the actual
--    live database column and all Python code (streamer_queries.py,
--    live_commands.py, migrations.py all reference twitch_user_id).
--
-- 2. discord_user_id added — live_role_cog uses it for direct member matching
--    without relying on nickname scanning.
--
-- 3. is_live, title, game_name, viewer_count, last_updated added — these are
--    written by streamer_queries.set_stream_live() / set_stream_offline().
--
-- 4. guild_id made nullable — a broadcaster can be tracked across multiple
--    guilds. EventSub subscriptions are per-broadcaster, not per-guild.
--    Notifications fan out to all guilds via guild_configs at dispatch time.
--
-- 5. All TIMESTAMP → TIMESTAMPTZ (timezone-aware).
--
-- 6. Indexes added for twitch_login (event payloads arrive as login string),
--    is_live partial index (monitor polls this every 60 seconds), and guild_id.
-- =============================================================================

CREATE TABLE IF NOT EXISTS streamers (

    id              BIGSERIAL   PRIMARY KEY,

    -- Twitch numeric user ID stored as TEXT (matches Twitch API + EventSub)
    twitch_user_id  TEXT        NOT NULL,

    -- Lowercased login handle, e.g. "neledraaa"
    twitch_login    TEXT        NOT NULL,

    -- Optional Discord member link for reliable role assignment
    -- Falls back to nickname scanning if NULL
    discord_user_id BIGINT,

    -- Guild that added this broadcaster (informational)
    -- Notifications fan out to all guilds via guild_configs at dispatch time
    guild_id        BIGINT,

    -- Live state — kept in sync by EventSub and the StreamMonitor poll loop
    is_live         BOOLEAN     NOT NULL DEFAULT FALSE,
    title           TEXT,
    game_name       TEXT,
    viewer_count    INTEGER,
    last_updated    TIMESTAMPTZ,

    -- Optional per-streamer channel override
    target_channel_id BIGINT,

    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE (twitch_user_id)
);

-- ── Indexes ───────────────────────────────────────────────────────────────────

-- Login lookups — event payloads arrive as login string
CREATE INDEX IF NOT EXISTS idx_streamers_login
    ON streamers (twitch_login);

-- Partial index — monitor polls live streamers every cycle (tiny + fast)
CREATE INDEX IF NOT EXISTS idx_streamers_live
    ON streamers (is_live)
    WHERE is_live = TRUE;

-- Guild lookups — admin commands, per-guild streamer lists
CREATE INDEX IF NOT EXISTS idx_streamers_guild
    ON streamers (guild_id);
