CREATE TABLE IF NOT EXISTS streamers (
    twitch_user_id TEXT PRIMARY KEY,
    twitch_login TEXT NOT NULL,

    guild_id BIGINT NOT NULL,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
