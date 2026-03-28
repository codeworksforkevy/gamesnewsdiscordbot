-- =============================================================================
-- database/guild_configs.sql
-- Guild-level notification and feature settings.
-- One row per Discord guild. This is the single source of truth for all
-- per-guild configuration read by guild_settings.get_guild_config().
-- =============================================================================
-- FIXES vs original:
--
-- 1. Missing games_channel_id — guild_settings.py explicitly reads this
--    column and falls back to announce_channel_id when it is NULL.
--    Without it every guild_configs query returned a dict missing the key,
--    causing a KeyError in any code path that checked games_channel_id.
--
-- 2. Missing enable_ping — event_router.py and stream_events.py both gate
--    role mentions behind config.get("enable_ping"). The column didn't exist
--    so it always evaluated to None (falsy) and pings were permanently
--    silenced regardless of what the guild wanted.
--
-- 3. TIMESTAMP → TIMESTAMPTZ — bare TIMESTAMP stores no timezone. Python's
--    datetime.now(timezone.utc) is timezone-aware; comparing it against a
--    naive DB timestamp produces asyncpg warnings and can cause wrong
--    ordering when daylight saving shifts occur.
--
-- 4. enable_epic / enable_gog / enable_steam defaulted to TRUE — meaning
--    every new guild would immediately start receiving Epic, GOG, and Steam
--    game deal notifications without ever asking for them. Changed to FALSE
--    so guilds opt in rather than opt out.
--
-- 5. No updated_at trigger — updated_at was a plain column with a static
--    DEFAULT. It was never updated automatically; every UPDATE on the row
--    left updated_at frozen at the insert time, making it useless for
--    "when was this config last changed" queries.
--
-- 6. No NOT NULL on notify_enabled / enable_* — these are boolean flags used
--    in conditional logic. A NULL boolean is neither TRUE nor FALSE and breaks
--    every Python check like `if config["notify_enabled"]`. Added NOT NULL.
-- =============================================================================

CREATE TABLE IF NOT EXISTS guild_configs (

    guild_id BIGINT PRIMARY KEY,

    -- Stream live/offline notification channel
    announce_channel_id BIGINT,

    -- Free games / deals / Luna posts channel
    -- NULL → falls back to announce_channel_id (handled in guild_settings.py)
    games_channel_id    BIGINT,

    -- Role pinged when a stream goes live (requires enable_ping = TRUE)
    ping_role_id        BIGINT,

    -- Role assigned to streamers while they are live (managed by live_role_cog)
    live_role_id        BIGINT,

    -- Master switch: disable to silence all notifications for this guild
    notify_enabled  BOOLEAN NOT NULL DEFAULT TRUE,

    -- Ping role on stream-live notifications
    enable_ping     BOOLEAN NOT NULL DEFAULT TRUE,

    -- Free game deal notifications (opt-in)
    enable_epic     BOOLEAN NOT NULL DEFAULT FALSE,
    enable_gog      BOOLEAN NOT NULL DEFAULT FALSE,
    enable_steam    BOOLEAN NOT NULL DEFAULT FALSE,

    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ── Trigger: keep updated_at current automatically ────────────────────────────

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
