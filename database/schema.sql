-- =========================
-- GUILD CONFIGS
-- =========================
CREATE TABLE IF NOT EXISTS guild_configs (
    guild_id BIGINT PRIMARY KEY,

    announce_channel_id BIGINT,
    ping_role_id BIGINT,
    live_role_id BIGINT,

    notify_enabled BOOLEAN DEFAULT TRUE,

    enable_epic BOOLEAN DEFAULT TRUE,
    enable_gog BOOLEAN DEFAULT TRUE,
    enable_steam BOOLEAN DEFAULT TRUE,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- =========================
-- STREAMERS (MULTI-GUILD FIX)
-- =========================
CREATE TABLE IF NOT EXISTS streamers (
    id SERIAL PRIMARY KEY,

    guild_id BIGINT NOT NULL,

    twitch_user_id TEXT NOT NULL,
    twitch_login TEXT NOT NULL,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    UNIQUE (guild_id, twitch_user_id)
);

CREATE INDEX IF NOT EXISTS idx_streamers_guild
ON streamers(guild_id);

-- =========================
-- STREAMER STATES (GLOBAL CACHE)
-- =========================
CREATE TABLE IF NOT EXISTS streamer_states (
    twitch_user_id TEXT PRIMARY KEY,

    is_live BOOLEAN DEFAULT FALSE,

    title TEXT,
    game_name TEXT,
    viewer_count INTEGER,

    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_streamer_states_live
ON streamer_states(is_live);
