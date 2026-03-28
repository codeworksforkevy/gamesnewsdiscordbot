# services/guild_config.py
#
# Düzeltmeler:
# - "channel_id" kolonu → "announce_channel_id" olarak güncellendi.
#   Eski kod channel_id yazıyordu; tüm yeni kod announce_channel_id bekliyor.
# - get_guild_config artık db.guild_settings singleton'ını kullanıyor
#   (db parametresi almak yerine) — tüm diğer callerlarla tutarlı.
# - upsert_guild_config hem guild_configs hem guild_settings'e yazıyor
#   böylece /live set-channel ile yazılan veri her iki tablodan okunabiliyor.

import logging
from typing import Optional

logger = logging.getLogger("guild-config")


# ==================================================
# GET CONFIG
# ==================================================

async def get_guild_config(db, guild_id: int) -> Optional[dict]:
    """
    guild_configs tablosunu okur, bulamazsa guild_settings'e bakar.
    db parametresi geriye dönük uyumluluk için korundu ama
    db.guild_settings singleton'ı da çalışır.
    """
    try:
        row = await db.fetchrow(
            """
            SELECT
                guild_id,
                announce_channel_id,
                games_channel_id,
                ping_role_id,
                live_role_id,
                notify_enabled,
                enable_ping,
                enable_epic,
                enable_gog,
                enable_steam
            FROM guild_configs
            WHERE guild_id = $1
            """,
            guild_id,
        )

        if row:
            d = dict(row)
            if not d.get("games_channel_id"):
                d["games_channel_id"] = d.get("announce_channel_id")
            return d

        # Legacy fallback
        row = await db.fetchrow(
            """
            SELECT guild_id, announce_channel_id, games_channel_id
            FROM guild_settings
            WHERE guild_id = $1
            """,
            guild_id,
        )

        if row:
            d = dict(row)
            if not d.get("games_channel_id"):
                d["games_channel_id"] = d.get("announce_channel_id")
            return d

        return None

    except Exception as e:
        logger.error(
            f"get_guild_config failed for guild {guild_id}: {e}",
            extra={"extra_data": {"guild_id": guild_id, "error": str(e)}},
        )
        return None


# ==================================================
# UPSERT CONFIG
# ==================================================

async def upsert_guild_config(
    db,
    guild_id: int,
    channel_id: int,                  # announce_channel_id olarak kaydedilir
    ping_role_id: int | None = None,
    live_role_id: int | None = None,
    enable_ping: bool = True,
) -> None:
    """
    guild_configs ve guild_settings tablolarına yazar.
    channel_id parametresi announce_channel_id olarak saklanır.
    """
    try:
        await db.execute(
            """
            INSERT INTO guild_configs (
                guild_id,
                announce_channel_id,
                ping_role_id,
                live_role_id,
                enable_ping
            )
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (guild_id) DO UPDATE SET
                announce_channel_id = EXCLUDED.announce_channel_id,
                ping_role_id        = EXCLUDED.ping_role_id,
                live_role_id        = EXCLUDED.live_role_id,
                enable_ping         = EXCLUDED.enable_ping,
                updated_at          = NOW()
            """,
            guild_id,
            channel_id,
            ping_role_id,
            live_role_id,
            enable_ping,
        )

        # guild_settings'e de yaz — /live set-channel tutarlı kalsın
        await db.execute(
            """
            INSERT INTO guild_settings (guild_id, announce_channel_id)
            VALUES ($1, $2)
            ON CONFLICT (guild_id) DO UPDATE SET
                announce_channel_id = EXCLUDED.announce_channel_id
            """,
            guild_id,
            channel_id,
        )

    except Exception as e:
        logger.error(
            f"upsert_guild_config failed for guild {guild_id}: {e}",
            extra={"extra_data": {"guild_id": guild_id, "error": str(e)}},
        )
