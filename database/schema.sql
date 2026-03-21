CREATE TABLE IF NOT EXISTS guild_configs (
    guild_id BIGINT PRIMARY KEY,
    ping_role_id BIGINT,
    live_role_id BIGINT,
    announce_channel_id BIGINT
);

CREATE TABLE IF NOT EXISTS streamers (
    twitch_user_id TEXT PRIMARY KEY,
    twitch_login TEXT,
    guild_id BIGINT
);
