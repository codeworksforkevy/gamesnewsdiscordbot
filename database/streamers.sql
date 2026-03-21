CREATE TABLE IF NOT EXISTS streamers (
    broadcaster_id TEXT PRIMARY KEY,
    is_live BOOLEAN DEFAULT FALSE,
    title TEXT,
    game_name TEXT,
    last_updated TIMESTAMP
);
