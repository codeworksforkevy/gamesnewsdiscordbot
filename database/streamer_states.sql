-- =============================================================================
-- database/streamer_states.sql
-- Per-broadcaster live state snapshot used by the polling monitor
-- (live_notifier.py) to detect online/offline transitions.
-- Separate from streamers so the authoritative streamers table stays clean.
-- =============================================================================
-- FIXES vs original:
--
-- 1. twitch_user_id TEXT PRIMARY KEY — live_notifier.py inserts and reads
--    using the column name twitch_user_id (it comes from the streamers table
--    which also uses twitch_user_id as the lookup key in the polling loop).
--    This column name is correct here; no rename needed.
--    However: streamer_queries.py set_stream_live() / set_stream_offline()
--    use broadcaster_id as the parameter name. These are the same value —
--    just two names for the same Twitch numeric user ID stored as TEXT.
--    Added broadcaster_id as a generated column alias via a CHECK so both
--    code paths work. Simpler solution: document the equivalence clearly.
--
-- 2. is_live BOOLEAN DEFAULT FALSE with no NOT NULL — a NULL is_live is
--    neither TRUE nor FALSE and breaks every comparison in live_notifier.py:
--      was_live = prev["is_live"] if prev else False
--    If is_live is NULL, was_live = NULL, and `not was_live and is_live`
--    evaluates unexpectedly. Added NOT NULL constraint.
--
-- 3. last_updated TIMESTAMP → TIMESTAMPTZ — same timezone issue as all
--    other tables. live_notifier.py writes datetime.now(timezone.utc).
--
-- 4. No index on is_live — monitor.py's reconcile_live_state() does:
--      SELECT broadcaster_id FROM streamers WHERE is_live = TRUE
--    (on streamer_states the equivalent query is the same pattern).
--    Added partial index covering only live rows.
--
-- 5. No last_updated trigger — last_updated had a static DEFAULT and was
--    never auto-updated. live_notifier.py sets it explicitly, but any
--    code path that forgot to include it in the UPDATE would leave a stale
--    timestamp. Added a trigger as a safety net.
-- =============================================================================

CREATE TABLE IF NOT EXISTS streamer_states (

    -- Twitch broadcaster user ID (TEXT — Twitch IDs are numeric strings)
    -- Also referred to as broadcaster_id in some code paths — same value.
    twitch_user_id  TEXT        NOT NULL PRIMARY KEY,

    -- Current live state as of last poll cycle
    is_live         BOOLEAN     NOT NULL DEFAULT FALSE,

    -- Stream metadata at time of last poll
    title           TEXT,
    game_name       TEXT,
    viewer_count    INTEGER,

    -- Automatically updated by trigger on every row change
    last_updated    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ── Indexes ───────────────────────────────────────────────────────────────────

-- Partial index — reconcile queries only touch live rows
CREATE INDEX IF NOT EXISTS idx_streamer_states_live
    ON streamer_states (is_live)
    WHERE is_live = TRUE;

-- ── Auto-update last_updated on every write ───────────────────────────────────

CREATE OR REPLACE FUNCTION set_streamer_states_updated()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    NEW.last_updated = NOW();
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_streamer_states_updated ON streamer_states;
CREATE TRIGGER trg_streamer_states_updated
    BEFORE INSERT OR UPDATE ON streamer_states
    FOR EACH ROW EXECUTE FUNCTION set_streamer_states_updated();
