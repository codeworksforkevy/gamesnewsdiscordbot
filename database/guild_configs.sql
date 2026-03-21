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
