-- =============================================================================
-- live_migration.sql  —  TEK SEFERLIK ÇALIŞTIR
-- Railway → Postgres servisi → Query sekmesi → Yapıştır → Run
--
-- Ne yapar:
--   1. guild_configs tablosundaki "channel_id" kolonunu "announce_channel_id"
--      olarak yeniden adlandırır (eski kod channel_id yazıyordu, yeni kod
--      announce_channel_id bekliyor)
--   2. Eksik kolonları ekler (games_channel_id, notify_enabled, enable_ping vb.)
--   3. Kanalını direkt INSERT eder — 1446562626695074006
--   4. Diğer eksik tabloları oluşturur
--   5. Mevcut streamers verilerine dokunmaz
-- =============================================================================

BEGIN;

-- ── 1. guild_configs tablosu var mı kontrol et, yoksa oluştur ────────────────
CREATE TABLE IF NOT EXISTS guild_configs (
    guild_id            BIGINT  NOT NULL PRIMARY KEY,
    announce_channel_id BIGINT,
    games_channel_id    BIGINT,
    ping_role_id        BIGINT,
    live_role_id        BIGINT,
    notify_enabled      BOOLEAN NOT NULL DEFAULT TRUE,
    enable_ping         BOOLEAN NOT NULL DEFAULT TRUE,
    enable_epic         BOOLEAN NOT NULL DEFAULT FALSE,
    enable_gog          BOOLEAN NOT NULL DEFAULT FALSE,
    enable_steam        BOOLEAN NOT NULL DEFAULT FALSE,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ── 2. Eski "channel_id" kolonunu "announce_channel_id" olarak yeniden adlandır
--       (eğer hâlâ eski adıyla duruyorsa)
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'guild_configs' AND column_name = 'channel_id'
    ) AND NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'guild_configs' AND column_name = 'announce_channel_id'
    ) THEN
        ALTER TABLE guild_configs RENAME COLUMN channel_id TO announce_channel_id;
        RAISE NOTICE 'channel_id → announce_channel_id olarak yeniden adlandırıldı';
    ELSE
        RAISE NOTICE 'Kolon zaten doğru adda veya dönüşüm gerekmedi';
    END IF;
END;
$$;

-- ── 3. Eksik kolonları ekle (IF NOT EXISTS — zaten varsa hata vermez) ─────────
ALTER TABLE guild_configs ADD COLUMN IF NOT EXISTS announce_channel_id BIGINT;
ALTER TABLE guild_configs ADD COLUMN IF NOT EXISTS games_channel_id    BIGINT;
ALTER TABLE guild_configs ADD COLUMN IF NOT EXISTS ping_role_id        BIGINT;
ALTER TABLE guild_configs ADD COLUMN IF NOT EXISTS live_role_id        BIGINT;
ALTER TABLE guild_configs ADD COLUMN IF NOT EXISTS notify_enabled      BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE guild_configs ADD COLUMN IF NOT EXISTS enable_ping         BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE guild_configs ADD COLUMN IF NOT EXISTS enable_epic         BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE guild_configs ADD COLUMN IF NOT EXISTS enable_gog          BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE guild_configs ADD COLUMN IF NOT EXISTS enable_steam        BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE guild_configs ADD COLUMN IF NOT EXISTS created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW();
ALTER TABLE guild_configs ADD COLUMN IF NOT EXISTS updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW();

-- ── 4. updated_at trigger ─────────────────────────────────────────────────────
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

-- ── 5. guild_settings tablosu (legacy, /live set-channel buraya yazar) ────────
CREATE TABLE IF NOT EXISTS guild_settings (
    guild_id            BIGINT NOT NULL PRIMARY KEY,
    announce_channel_id BIGINT,
    games_channel_id    BIGINT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ── 6. guild_notification_channels ───────────────────────────────────────────
CREATE TABLE IF NOT EXISTS guild_notification_channels (
    id          BIGSERIAL   PRIMARY KEY,
    guild_id    BIGINT      NOT NULL,
    channel_id  BIGINT      NOT NULL,
    is_active   BOOLEAN     NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (guild_id, channel_id)
);

-- ── 7. streamer_states ────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS streamer_states (
    twitch_user_id  TEXT        NOT NULL PRIMARY KEY,
    is_live         BOOLEAN     NOT NULL DEFAULT FALSE,
    title           TEXT,
    game_name       TEXT,
    viewer_count    INTEGER,
    last_updated    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ── 8. streamers tablosuna eksik kolonları ekle ───────────────────────────────
ALTER TABLE streamers ADD COLUMN IF NOT EXISTS is_live      BOOLEAN     NOT NULL DEFAULT FALSE;
ALTER TABLE streamers ADD COLUMN IF NOT EXISTS title        TEXT;
ALTER TABLE streamers ADD COLUMN IF NOT EXISTS game_name    TEXT;
ALTER TABLE streamers ADD COLUMN IF NOT EXISTS viewer_count INTEGER;
ALTER TABLE streamers ADD COLUMN IF NOT EXISTS last_updated TIMESTAMPTZ;

-- ── 9. KevKevvy's Plaza konfigürasyonunu yaz ─────────────────────────────────
--       Guild:           1446560723122520207
--       Stream kanalı:   1446562626695074006
--       Oyun kanalı:     1450903610559823873
INSERT INTO guild_configs (
    guild_id,
    announce_channel_id,
    games_channel_id,
    notify_enabled,
    enable_ping
)
VALUES (
    1446560723122520207,
    1446562626695074006,
    1450903610559823873,
    TRUE,
    FALSE
)
ON CONFLICT (guild_id) DO UPDATE SET
    announce_channel_id = EXCLUDED.announce_channel_id,
    games_channel_id    = EXCLUDED.games_channel_id,
    notify_enabled      = EXCLUDED.notify_enabled,
    updated_at          = NOW();

-- guild_settings'e de yaz (/live set-channel tutarlı kalsın)
INSERT INTO guild_settings (guild_id, announce_channel_id, games_channel_id)
VALUES (1446560723122520207, 1446562626695074006, 1450903610559823873)
ON CONFLICT (guild_id) DO UPDATE SET
    announce_channel_id = EXCLUDED.announce_channel_id,
    games_channel_id    = EXCLUDED.games_channel_id;

-- ── 10. Migration kaydı ───────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS schema_migrations (
    version     TEXT        PRIMARY KEY,
    applied_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO schema_migrations (version) VALUES ('live_migration_2026_03_28')
    ON CONFLICT (version) DO NOTHING;

COMMIT;

-- Doğrulama: Bunlar doğru değerleri göstermeli
SELECT guild_id, announce_channel_id, games_channel_id, notify_enabled
FROM guild_configs
WHERE guild_id = 1446560723122520207;
