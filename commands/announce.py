# commands/announce.py
import logging
import re
from datetime import datetime, timezone, timedelta
import discord
from discord import app_commands

logger = logging.getLogger("announce")

ANNOUNCE_CHANNEL_ID = 1446561786743488643
KEVY_TWITCH = "https://twitch.tv/kevkevvy"

def _parse_time(time_str: str) -> datetime | None:
    time_str = time_str.strip().lower()
    m = re.match(r"^(\d{1,2}):(\d{2})$", time_str)
    if m:
        hour, minute = int(m.group(1)), int(m.group(2))
    elif re.match(r"^\d{1,2}$", time_str):
        hour, minute = int(time_str), 0
    else:
        return None

    now = datetime.now(timezone.utc)
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target < now:
        target += timedelta(days=1)
    return target

async def register(bot, app_state, session):
    @bot.tree.command(name="announce", description="⚠️ (Admin) Kevy için manuel stream duyurusu atar.")
    @app_commands.default_permissions(manage_guild=True)
    async def announce_cmd(interaction: discord.Interaction, game: str, time_str: str = None):
        await interaction.response.defer(ephemeral=True)

        try:
            channel = interaction.guild.get_channel(ANNOUNCE_CHANNEL_ID) or await bot.fetch_channel(ANNOUNCE_CHANNEL_ID)
        except Exception:
            await interaction.followup.send("❌ Duyuru kanalı bulunamadı. ID'yi kontrol et.", ephemeral=True)
            return

        go_live_ts = None
        if time_str:
            dt = _parse_time(time_str)
            if not dt:
                await interaction.followup.send("❌ Saat formatı hatalı (Örn: 21:00 veya 21 yaz).", ephemeral=True)
                return
            go_live_ts = int(dt.timestamp())

        desc = f"🎮 Oyun: **{game}**\n"
        if go_live_ts:
            desc += f"⏰ Başlıyor: <t:{go_live_ts}:R>"
        else:
            desc += "🔴 Şu an yayında!"

        embed = discord.Embed(
            title="Kevy Yayın Duyurusu!",
            description=desc,
            color=0xFFB6C1, # Baby Pink
            url=KEVY_TWITCH
        )

        content = None
        # Rol çakışmalarını önlemek için güvenli arama
        live_role = discord.utils.get(interaction.guild.roles, name="🟢 Live")
        if not live_role:
            try:
                live_role = await interaction.guild.create_role(
                    name="🟢 Live", color=discord.Color.green(), mentionable=True, reason="Auto-created by Find a Curie /announce"
                )
            except discord.Forbidden:
                logger.warning("🟢 Live rolü oluşturmak için yetkim yok.")

        if live_role:
            content = live_role.mention

        try:
            await channel.send(content=content, embed=embed)
            await interaction.followup.send("✅ Duyuru başarıyla gönderildi!", ephemeral=True)
        except Exception as e:
            logger.error(f"/announce hatası: {e}")
            await interaction.followup.send("❌ Mesaj gönderilemedi, yetkilerimi kontrol et.", ephemeral=True)

    logger.info("announce command registered")
