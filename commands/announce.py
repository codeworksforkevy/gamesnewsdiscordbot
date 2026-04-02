# commands/announce.py
#
# /announce — Kevy'nin stream duyuru komutu
#
# Sadece sunucu admini kullanabilir.
# go_live_at girilirse Discord timestamp'e çevirir (herkes kendi saatinde görür).
# Boş bırakılırsa "şu an yayında" olarak post atar.
# Post gideceği kanal: 1446561786743488643

import logging
import re
from datetime import datetime, timezone, timedelta

import discord
from discord import app_commands

logger = logging.getLogger("announce")

# Duyuruların gideceği kanal
ANNOUNCE_CHANNEL_ID = 1446561786743488643

# Kevy'nin Twitch linki
KEVY_TWITCH = "https://twitch.tv/kevkevvy"


# ──────────────────────────────────────────────────────────────
# ZAMAN PARSER
# ──────────────────────────────────────────────────────────────

def _parse_time(time_str: str) -> datetime | None:
    """
    "21:00", "21:30", "9pm", "21" gibi formatları bugünün UTC datetime'ına çevirir.
    Geçmiş bir saat girilirse otomatik olarak yarına atar.
    """
    time_str = time_str.strip().lower()

    # "21:00" veya "21:30"
    m = re.match(r"^(\d{1,2}):(\d{2})$", time_str)
    if m:
        hour, minute = int(m.group(1)), int(m.group(2))
    else:
        # "21" veya "9pm" / "9am"
        m2 = re.match(r"^(\d{1,2})(am|pm)?$", time_str)
        if not m2:
            return None
        hour   = int(m2.group(1))
        suffix = m2.group(2)
        minute = 0
        if suffix == "pm" and hour != 12:
            hour += 12
        elif suffix == "am" and hour == 12:
            hour = 0

    if hour > 23 or minute > 59:
        return None

    now = datetime.now(timezone.utc)
    dt  = now.replace(hour=hour, minute=minute, second=0, microsecond=0)

    # Geçmiş saatse yarına at
    if dt <= now:
        dt += timedelta(days=1)

    return dt


# ──────────────────────────────────────────────────────────────
# EMBED BUILDER
# ──────────────────────────────────────────────────────────────

def _build_announce_embed(
    user_info:   dict | None,
    message:     str,
    game:        str | None,
    go_live_ts:  int | None,   # Unix timestamp, None = live right now
) -> discord.Embed:
    """
    Type 2 stili — baby blue, canlı göstergeli.
    go_live_ts=None → "LIVE NOW", aksi halde Discord timestamp.
    """
    is_live_now = go_live_ts is None

    embed = discord.Embed(
        description=f"*{message}*",
        color=0x89CFF0,   # baby blue
        url=KEVY_TWITCH,
    )

    # Author: profil resmi + isim
    icon_url = user_info.get("profile_image_url") if user_info else None
    embed.set_author(
        name="kevkevvy is live!" if is_live_now else "kevkevvy",
        url=KEVY_TWITCH,
        icon_url=icon_url,
    )

    # Oyun alanı
    if game:
        embed.add_field(name="🕹️ Game", value=game, inline=True)

    # Zaman alanı
    if is_live_now:
        embed.add_field(
            name="📺 Watch",
            value=f"[twitch.tv/kevkevvy]({KEVY_TWITCH})",
            inline=True,
        )
    else:
        embed.add_field(
            name="🕐 Going live",
            value=f"<t:{go_live_ts}:F> (<t:{go_live_ts}:R>)",
            inline=False,
        )
        embed.add_field(
            name="📺 Link",
            value=f"[twitch.tv/kevkevvy]({KEVY_TWITCH})",
            inline=True,
        )

    embed.set_footer(text="Vibes: Very Cool")
    embed.timestamp = discord.utils.utcnow()
    return embed


# ──────────────────────────────────────────────────────────────
# REGISTER
# ──────────────────────────────────────────────────────────────

async def register(bot, app_state, session):

    @bot.tree.command(
        name="announce",
        description="📣 Stream duyurusu at (sadece admin)",
    )
    @app_commands.describe(
        message="Duyuru mesajı — stream başlığın veya bir not",
        game="Oynayacağın oyun (opsiyonel)",
        go_live_at="Yayın saati — ör: 21:00 | Boş bırakırsan şu an canlı olarak post atar",
        ping="@🟢 Live rolünü ping'le (varsayılan: evet)",
    )
    async def announce_command(
        interaction: discord.Interaction,
        message: str,
        game: str | None = None,
        go_live_at: str | None = None,
        ping: bool = True,
    ):
        # ── Sadece admin ──────────────────────────────────────────────────
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(
                "❌ Bu komutu sadece sunucu admini kullanabilir.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)

        # ── Zaman parse et ────────────────────────────────────────────────
        go_live_ts = None
        if go_live_at:
            dt = _parse_time(go_live_at)
            if dt is None:
                await interaction.followup.send(
                    "❌ Saat formatı tanınamadı. Şu formatları kullanabilirsin: `21:00`, `21`, `9pm`",
                    ephemeral=True,
                )
                return
            go_live_ts = int(dt.timestamp())

        # ── Kullanıcı bilgisi çek (profil resmi için) ─────────────────────
        user_info = None
        try:
            api = app_state.twitch_api
            if api:
                user_info = await api.get_user_by_login("kevkevvy")
        except Exception as e:
            logger.warning(f"Could not fetch kevkevvy user info: {e}")

        # ── Embed oluştur ─────────────────────────────────────────────────
        embed = _build_announce_embed(user_info, message, game, go_live_ts)

        # ── Kanalı bul ────────────────────────────────────────────────────
        channel = (
            interaction.guild.get_channel(ANNOUNCE_CHANNEL_ID)
            or await bot.fetch_channel(ANNOUNCE_CHANNEL_ID)
        )

        if not channel:
            await interaction.followup.send(
                f"❌ Duyuru kanalı ({ANNOUNCE_CHANNEL_ID}) bulunamadı.",
                ephemeral=True,
            )
            return

        # ── Ping rolü ─────────────────────────────────────────────────────
        content = None
        if ping:
            live_role = discord.utils.get(interaction.guild.roles, name="🟢 Live")
            if live_role:
                content = live_role.mention
            else:
                # Rol yoksa oluştur
                try:
                    live_role = await interaction.guild.create_role(
                        name="🟢 Live",
                        color=discord.Color.green(),
                        mentionable=True,
                        reason="Auto-created by Find a Curie /announce",
                    )
                    content = live_role.mention
                    logger.info(f"Created 🟢 Live role in {interaction.guild.name}")
                except Exception as e:
                    logger.warning(f"Could not create Live role: {e}")

        # ── Post at ───────────────────────────────────────────────────────
        try:
            await channel.send(content=content, embed=embed)
            logger.info(
                f"/announce used by {interaction.user} — "
                f"game={game!r} go_live_at={go_live_at!r}"
            )
            time_str = (
                f"<t:{go_live_ts}:F>" if go_live_ts
                else "şu an (live now)"
            )
            await interaction.followup.send(
                f"✅ Duyuru gönderildi! Zaman: {time_str}",
                ephemeral=True,
            )
        except discord.Forbidden:
            await interaction.followup.send(
                f"❌ {channel.mention} kanalına yazma iznim yok.",
                ephemeral=True,
            )
        except Exception as e:
            logger.error(f"/announce failed: {e}")
            await interaction.followup.send(
                "❌ Bir hata oluştu. Tekrar dene.",
                ephemeral=True,
            )
