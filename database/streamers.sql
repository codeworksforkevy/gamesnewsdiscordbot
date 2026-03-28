-- =============================================================================
-- database/streamers.sql
-- One row per tracked Twitch broadcaster.
-- Guild-level settings (channel, roles) live in guild_configs — not here.
-- =============================================================================
-- FIXES vs original (streamers.sql standalone):
--
-- 1. twitch_user_id TEXT PRIMARY KEY — broadcaster_id is the correct Twitch
--    field name used in every EventSub payload and throughout the Python code
--    (streamer_queries.py, monitor.py, eventsub_manager.py all reference
--    "broadcaster_id"). Using a different name here meant every query that
--    joined or compared against the EventSub payload had to rename the field.
--    Changed: primary key column renamed to broadcaster_id while keeping
--    twitch_user_id as a generated alias column for backward compat.
--    Update: named broadcaster_id as primary, twitch_user_id as alias view
--    would add complexity — instead we rename to broadcaster_id and note it.
--
-- 2. Missing discord_user_id — live_role_cog.py checks payload.get(
--    "discord_user_id") for direct member matching. Without this column
--    the cog always fell back to the unreliable nickname scan.
--
-- 3. Missing is_live, title, game_name, viewer_count, last_updated —
--    streamer_queries.py writes all five in set_stream_live() / set_stream_offline()
--    and monitor.py reads is_live constantly. None of these columns existed
--    in the standalone streamers.sql, causing column-not-found errors on
--    every live-state update.
--
-- 4. guild_id NOT NULL — a broadcaster can be tracked globally (EventSub is
--    per-broadcaster, not per-guild). Making guild_id NOT NULL forces every
--    broadcaster to belong to exactly one guild, which breaks multi-guild
--    setups where the same streamer is watched by multiple guilds. Changed
--    to nullable; the guild_id column becomes "the guild that added this
--    broadcaster" for record-keeping, while notifications fan out via
--    guild_configs at dispatch time.
--
-- 5. TIMESTAMP → TIMESTAMPTZ — same timezone-awareness issue as other tables.
--
-- 6. No indexes beyond the PK — monitor.py queries WHERE is_live = TRUE
--    on every cycle. Without an index this is a full table scan every 180s.
--    Added a partial index that only covers live rows (tiny, fast).
--    Also added an index on twitch_login for event_router lookups by login.
-- =============================================================================

CREATE TABLE IF NOT EXISTS streamers (

    -- Primary identifier matching Twitch API + EventSub payloads
    broadcaster_id  TEXT    NOT NULL PRIMARY KEY,

    -- Human-readable login handle (lowercased, e.g. "ninja")
    twitch_login    TEXT    NOT NULL,

    -- Optional: which Discord member this streamer maps to
    -- Used by live_role_cog for reliable role assignment without nickname scanning
    discord_user_id BIGINT,

    -- Which guild added this broadcaster (informational; notifications fan out
    -- to ALL guilds via guild_configs at dispatch time)
    guild_id        BIGINT,

    -- ── Live state ──────────────────────────────────────────────────────────
    -- Kept in sync by EventSub (eventsub_server.py) and reconciled by
    -- monitor.py every cycle.

    is_live         BOOLEAN     NOT NULL DEFAULT FALSE,
    title           TEXT,
    game_name       TEXT,
    viewer_count    INTEGER,
    last_updated    TIMESTAMPTZ,

    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ── Indexes ───────────────────────────────────────────────────────────────────

-- Login lookups from event_router / stream_events (received as login in payload)
CREATE INDEX IF NOT EXISTS idx_streamers_login
    ON streamers (twitch_login);

-- Partial index — monitor.py queries live streamers every cycle.
-- Covering only the TRUE rows keeps this index tiny regardless of total row count.
CREATE INDEX IF NOT EXISTS idx_streamers_live
    ON streamers (is_live)
    WHERE is_live = TRUE;

-- Guild lookups (admin commands, per-guild streamer lists)
CREATE INDEX IF NOT EXISTS idx_streamers_guild
    ON streamers (guild_id);
