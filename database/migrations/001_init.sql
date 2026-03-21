-- =================================================
-- EXTENSIONS
-- =================================================

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";


-- =================================================
-- STREAMERS TABLE
-- =================================================

CREATE TABLE IF NOT EXISTS streamers (

    guild_id BIGINT NOT NULL,
    broadcaster_id TEXT NOT NULL,

    channel_id BIGINT NOT NULL,
    role_id BIGINT,

    is_live BOOLEAN DEFAULT FALSE,

    last_title TEXT,
    last_game TEXT,

    message_id BIGINT,

    created_at TIMESTAMP DEFAULT NOW(),

    PRIMARY KEY (guild_id, broadcaster_id)
);


-- =================================================
-- GUILD CONFIG
-- =================================================

CREATE TABLE IF NOT EXISTS guild_config (

    guild_id BIGINT PRIMARY KEY,

    default_channel_id BIGINT,
    default_role_id BIGINT,

    language TEXT DEFAULT 'EN',
    ping_enabled BOOLEAN DEFAULT TRUE,

    created_at TIMESTAMP DEFAULT NOW()
);


-- =================================================
-- INDEXES (PERFORMANCE)
-- =================================================

CREATE INDEX IF NOT EXISTS idx_streamers_broadcaster
ON streamers (broadcaster_id);

CREATE INDEX IF NOT EXISTS idx_streamers_live
ON streamers (is_live);


-- =================================================
-- OPTIONAL: EVENT LOGGING (DEBUGGING)
-- =================================================

CREATE TABLE IF NOT EXISTS twitch_event_logs (

    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    event_type TEXT,
    broadcaster_id TEXT,

    payload JSONB,

    created_at TIMESTAMP DEFAULT NOW()
);
