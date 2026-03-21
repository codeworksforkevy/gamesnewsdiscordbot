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
-- STREAMERS (CONFIG)
-- =========================
CREATE TABLE IF NOT EXISTS streamers (
    twitch_user_id TEXT PRIMARY KEY,
    twitch_login TEXT NOT NULL,
    guild_id BIGINT NOT NULL,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- =========================
-- STREAMER STATES (RUNTIME)
-- =========================
CREATE TABLE IF NOT EXISTS streamer_states (
    twitch_user_id TEXT PRIMARY KEY,

    is_live BOOLEAN DEFAULT FALSE,

    title TEXT,
    game_name TEXT,
    viewer_count INTEGER,

    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
