import discord
from discord import app_commands
import logging
import asyncio
import time
from datetime import datetime, timezone

logger = logging.getLogger("live-commands")

# ==================================================
# TEK MERKEZ EMBED BUILDER (Tüm sistem burayı kullanmalı)
# ==================================================

def build_live_embed(stream: dict, user: dict = None) -> discord.Embed:
    # Verileri Twitch objesinden güvenle çekiyoruz
    login = stream.get("user_login") or (user.get("login") if user else "unknown")
    name = stream.get("user_name") or (user.get("display_name") if user else login)
    stream_title = stream.get("title", "No Title")
    game_name = stream.get("game_name") or stream.get("game") or "Creative / Art"
    
    if not game_name or str(game_name).lower() == "unknown":
        game_name = "Creative / Art"
        
    started_at = stream.get("started_at", "")
    stream_url = f"https://www.twitch.tv/{login}"

    ts_str = "now"
    if started_at:
        try:
            dt = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
            ts = int(dt.timestamp())
            ts_str = f"<t:{ts}:R>"
        except: pass

    # VIEWERS KESİNLİKLE YOK - BAŞLIK (PROJECT) EKLENDİ
    description = (
        f"🏋️🏋️ **Time to chill with Kevy!** 🏋️🏋️\n\n"
        f"Grab your pencils, the art class is starting! ✏️\n\n"
        f"👩‍🔬 **Project:** {stream_title}\n"
        f"👩‍💻 **Game:** `{game_name}`\n"
        f"☕ **Started:** {ts_str}"
    )

    embed = discord.Embed(
        title=f"🎬 {stream_title}",
        url=stream_url,
        description=description,
        color=0xFFB6C1, 
    )
    
    if user and user.get("profile_image_url"):
        embed.set_author(name=name, url=stream_url, icon_url=user.get("profile_image_url"))
    else:
        embed.set_author(name=name, url=stream_url)
    
    raw_thumb = stream.get("thumbnail_url", "")
    if raw_thumb:
        thumbnail = raw_thumb.replace("{width}", "1280").replace("{height}", "720")
        thumbnail += f"?v={int(time.time())}" 
        embed.set_image(url=thumbnail)

    embed.set_footer(text="🧪 Atmosphere: Very Cool")
    embed.timestamp = discord.utils.utcnow()
    return embed

def build_offline_embed(login: str, display_name: str, prev_state: dict) -> discord.Embed:
    now = datetime.now(timezone.utc)
    duration_str = "Unknown"
    started_at = prev_state.get("started_at")
    if started_at:
        try:
            start_dt = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
            diff = now - start_dt
            h, rem = divmod(int(diff.total_seconds()), 3600)
            m, s = divmod(rem, 60)
            duration_str = f"{h}h {m}m {s}s"
        except: pass

    embed = discord.Embed(
        title=f"{display_name} was live on Twitch",
        url=f"https://twitch.tv/{login}",
        description=f"*{prev_state.get('title', 'No title')}*", # Italic başlık
        color=0x2f3136, 
    )
    embed.add_field(name="👩‍💻 Game", value=prev_state.get("game", "Creative / Art"), inline=True)
    embed.add_field(name="⏱️ Duration", value=duration_str, inline=True)
    embed.add_field(name="🎬 VOD", value=f"[Click to watch](https://twitch.tv/{login}/videos)", inline=True)
    embed.set_footer(text=f"⚫ Stream ended • twitch.tv/{login}")
    embed.timestamp = now
    return embed

# ==================================================
# REGISTER & COMMANDS
# ==================================================

async def register(bot, app_state, session):
    group = app_commands.Group(name="live", description="Twitch tracking")

    @group.command(name="force-post", description="⚠️ Send instant announcement")
    async def force_post(interaction: discord.Interaction, twitch_login: str):
        await interaction.response.defer(ephemeral=True)
        login = twitch_login.lower().strip()
        live_streams = await app_state.twitch_api.get_streams_by_logins([login])
        
        if not live_streams:
            return await interaction.followup.send(f"👩‍🔬 **{login}** is not live.")
            
        stream = live_streams[0]
        user_info = await app_state.twitch_api.get_user_by_login(login)
        
        # Kanal belirleme
        row = await app_state.db.fetchrow("SELECT target_channel_id FROM streamers WHERE twitch_login = $1 AND guild_id = $2", login, interaction.guild_id)
        ch_id = row["target_channel_id"] if row and row["target_channel_id"] else None
        
        if not ch_id:
            from db.guild_settings import get_guild_config
            cfg = await get_guild_config(interaction.guild_id)
            ch_id = cfg.get("announce_channel_id") if cfg else None
            
        if not ch_id:
            return await interaction.followup.send("❌ No channel set.")

        channel = interaction.guild.get_channel(ch_id) or await bot.fetch_channel(ch_id)
        embed = build_live_embed(stream, user_info)
        await channel.send(embed=embed)
        await interaction.followup.send("✅ Forced post sent!")

    @group.command(name="sync", description="🔄 Sync commands for this server")
    async def sync_this(interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        await bot.tree.sync(guild=interaction.guild)
        await interaction.followup.send("✅ Commands synced for this server!")

    bot.tree.add_command(group)
    logger.info("Live commands registered")
