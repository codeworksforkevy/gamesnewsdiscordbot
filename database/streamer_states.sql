CREATE TABLE IF NOT EXISTS streamer_states (
    twitch_user_id TEXT PRIMARY KEY,

    is_live BOOLEAN DEFAULT FALSE,

    title TEXT,
    game_name TEXT,
    viewer_count INTEGER,

    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
