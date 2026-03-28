"""
db/migrations.py
────────────────────────────────────────────────────────────────
Bot başlarken otomatik çalışan migration sistemi.
Her migration idempotent (IF NOT EXISTS / ON CONFLICT) olduğu için
defalarca çalıştırmak güvenlidir.

main.py'de DB bağlandıktan hemen sonra çağır:
    from db.migrations import run_migrations
    await run_migrations(app_state.db)
"""

import logging
import os

logger = logging.getLogger("db.migrations")

# ──────────────────────────────────────────────────────────────
# GUILD & CHANNEL IDS (hardcoded fallback)
# Railway env var olarak da ayarlanabilir
# ──────────────────────────────────────────────────────────────

KEVKEVVY_GUILD_ID    = 1446560723122520207
STREAM_CHANNEL_ID    = 1446562626695074006
GAMES_CHANNEL_ID     = 1450903610559823873


async def run_migrations(db) -> None:
    """
    Tüm tabloları oluşturur, eksik kolonları ekler,
    ve guild konfigürasyonunu yazar.
    """
    logger.info("Running database migrations...")

    try:
        await _create_tables(db)
        await _fix_column_names(db)
        await _add_missing_columns(db)
        await _seed_guild_config(db)
        logger.info("✅ Database migrations complete")
    except Exception as e:
        logger.error(f"Migration failed: {e}", exc_info=True)
        raise


async def _create_tables(db) -> None:
    """Tüm tabloları oluşturur — zaten varsa dokunmaz."""

    await db.execute("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version    TEXT PRIMARY KEY,
            applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)

    await db.execute("""
        CREATE OR REPLACE FUNCTION set_updated_at()
        RETURNS TRIGGER LANGUAGE plpgsql AS $$
        BEGIN
            NEW.updated_at = NOW();
            RETURN NEW;
        END;
        $$
    """)

    await db.execute("""
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
        )
    """)

    await db.execute("""
        CREATE TABLE IF NOT EXISTS guild_settings (
            guild_id            BIGINT NOT NULL PRIMARY KEY,
            announce_channel_id BIGINT,
            games_channel_id    BIGINT,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)

    await db.execute("""
        CREATE TABLE IF NOT EXISTS guild_notification_channels (
            id         BIGSERIAL PRIMARY KEY,
            guild_id   BIGINT    NOT NULL,
            channel_id BIGINT    NOT NULL,
            is_active  BOOLEAN   NOT NULL DEFAULT TRUE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (guild_id, channel_id)
        )
    """)

    await db.execute("""
        CREATE TABLE IF NOT EXISTS streamer_states (
            twitch_user_id TEXT        NOT NULL PRIMARY KEY,
            is_live        BOOLEAN     NOT NULL DEFAULT FALSE,
            title          TEXT,
            game_name      TEXT,
            viewer_count   INTEGER,
            last_updated   TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)

    logger.info("Tables verified/created")


async def _fix_column_names(db) -> None:
    """
    Eski guild_config.py, guild_configs tablosunu 'channel_id' kolonuyla
    oluşturuyordu. Yeni kod 'announce_channel_id' bekliyor.
    Bu fonksiyon kolonu güvenli şekilde yeniden adlandırır.
    """
    try:
        row = await db.fetchrow("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = 'guild_configs'
              AND column_name = 'channel_id'
        """)

        if row:
            await db.execute(
                "ALTER TABLE guild_configs RENAME COLUMN channel_id TO announce_channel_id"
            )
            logger.info("guild_configs.channel_id → announce_channel_id renamed")

    except Exception as e:
        logger.warning(f"Column rename skipped (may already be done): {e}")


async def _add_missing_columns(db) -> None:
    """Eksik kolonları ekler — zaten varsa hata vermez."""

    guild_config_cols = [
        ("games_channel_id",  "BIGINT"),
        ("ping_role_id",      "BIGINT"),
        ("live_role_id",      "BIGINT"),
        ("notify_enabled",    "BOOLEAN NOT NULL DEFAULT TRUE"),
        ("enable_ping",       "BOOLEAN NOT NULL DEFAULT TRUE"),
        ("enable_epic",       "BOOLEAN NOT NULL DEFAULT FALSE"),
        ("enable_gog",        "BOOLEAN NOT NULL DEFAULT FALSE"),
        ("enable_steam",      "BOOLEAN NOT NULL DEFAULT FALSE"),
        ("updated_at",        "TIMESTAMPTZ NOT NULL DEFAULT NOW()"),
    ]

    for col, col_type in guild_config_cols:
        try:
            await db.execute(
                f"ALTER TABLE guild_configs ADD COLUMN IF NOT EXISTS {col} {col_type}"
            )
        except Exception:
            pass  # column already exists

    streamer_cols = [
        ("is_live",      "BOOLEAN NOT NULL DEFAULT FALSE"),
        ("title",        "TEXT"),
        ("game_name",    "TEXT"),
        ("viewer_count", "INTEGER"),
        ("last_updated", "TIMESTAMPTZ"),
    ]

    for col, col_type in streamer_cols:
        try:
            await db.execute(
                f"ALTER TABLE streamers ADD COLUMN IF NOT EXISTS {col} {col_type}"
            )
        except Exception:
            pass

    # updated_at trigger
    try:
        await db.execute("""
            DROP TRIGGER IF EXISTS trg_guild_configs_updated_at ON guild_configs
        """)
        await db.execute("""
            CREATE TRIGGER trg_guild_configs_updated_at
                BEFORE UPDATE ON guild_configs
                FOR EACH ROW EXECUTE FUNCTION set_updated_at()
        """)
    except Exception:
        pass

    logger.info("Columns verified/added")


async def _seed_guild_config(db) -> None:
    """
    Bilinen guild konfigürasyonunu yazar.
    ON CONFLICT DO UPDATE ile güvenli — varsa günceller.
    """

    # Env var'dan da okuyabilir — Railway'de değişken set edilirse öncelikli
    guild_id      = int(os.getenv("MAIN_GUILD_ID",       str(KEVKEVVY_GUILD_ID)))
    stream_ch     = int(os.getenv("STREAM_CHANNEL_ID",   str(STREAM_CHANNEL_ID)))
    games_ch      = int(os.getenv("GAMES_CHANNEL_ID",    str(GAMES_CHANNEL_ID)))

    await db.execute("""
        INSERT INTO guild_configs (
            guild_id, announce_channel_id, games_channel_id,
            notify_enabled, enable_ping
        )
        VALUES ($1, $2, $3, TRUE, FALSE)
        ON CONFLICT (guild_id) DO UPDATE SET
            announce_channel_id = EXCLUDED.announce_channel_id,
            games_channel_id    = EXCLUDED.games_channel_id,
            updated_at          = NOW()
    """, guild_id, stream_ch, games_ch)

    await db.execute("""
        INSERT INTO guild_settings (guild_id, announce_channel_id, games_channel_id)
        VALUES ($1, $2, $3)
        ON CONFLICT (guild_id) DO UPDATE SET
            announce_channel_id = EXCLUDED.announce_channel_id,
            games_channel_id    = EXCLUDED.games_channel_id
    """, guild_id, stream_ch, games_ch)

    await db.execute("""
        INSERT INTO schema_migrations (version)
        VALUES ('auto_migration_v1')
        ON CONFLICT (version) DO NOTHING
    """)

    logger.info(
        f"Guild config seeded — guild={guild_id} "
        f"stream_ch={stream_ch} games_ch={games_ch}"
    )
