import discord
from discord import app_commands
import logging
import asyncio
from datetime import datetime, timezone

logger = logging.getLogger("live-commands")

# ==================================================
# EMBED BUILDERS
# ==================================================

def build_live_embed(stream: dict, user: dict) -> discord.Embed:
    login      = stream.get("user_login") or user.get("login", "unknown")
    name       = stream.get("user_name")  or user.get("display_name", login)
    title      = stream.get("title", "Untitled stream")
    game       = stream.get("game_name", "Art / Creative")
    started_at = stream.get("started_at", "")
    stream_url = f"https://www.twitch.tv/{login}"

    ts_str = "nu / now"
    if started_at:
        try:
            dt = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
            ts = int(dt.timestamp())
            ts_str = f"<t:{ts}:R>"
        except: pass

    # Tam istediğin sıralama ve Belçika Flamancası (Vlaams) adaptasyonu
    description = (
        f"🇬🇧 🏋️🏋️ **Time to chill with Kevy!** 🏋️🏋️\n"
        f"🇧🇪 🏋️🏋️ **Tijd om te chillen met Kevy!** 🏋️🏋️\n\n"
        f"🇬🇧 Grab your pencils, the art class is starting! ✏️\n"
        f"🇧🇪 Pak je potloden, de tekenles begint! ✏️\n\n"
        f"👩‍🔬 **Project / Project:** {title}\n"
        f"👩‍💻 **Category / Categorie:** `{game}`\n"
        f"☕ **Started / Gestart:** {ts_str}"
    )

    embed = discord.Embed(
        title=f"🎬 {title}",
        url=stream_url,
        description=description,
        color=0xFFB6C1, 
    )

    # Author sadece streamer adı
    embed.set_author(name=name, url=stream_url, icon_url=user.get("profile_image_url"))

    raw_thumb = stream.get("thumbnail_url", "")
    if raw_thumb:
        thumbnail = raw_thumb.replace("{width}", "1280").replace("{height}", "720")
        embed.set_image(url=thumbnail)

    # Footer: İstediğin atmosfer bilgisi
    embed.set_footer(text="🧪 Atmosphere / Sfeer: Very Cool / Zeer Cool")
    embed.timestamp = discord.utils.utcnow()
    
    return embed

def build_offline_embed(login: str, display_name: str) -> discord.Embed:
    now_ts = int(datetime.now(timezone.utc).timestamp())
    embed = discord.Embed(
        title=f"{display_name} is now offline",
        description=f"Stream ended <t:{now_ts}:R>",
        color=0x808080,
    )
    embed.set_footer(text="⚫ Stream ended")
    return embed

# ==================================================
# STREAM MONITOR (ÇOKLU KANAL DESTEKLİ)
# ==================================================

class StreamMonitor:
    def __init__(self, bot, app_state):
        self.bot       = bot
        self.app_state = app_state
        self.db        = app_state.db
        self._state: dict = {}
        self._task = None

    def start(self):
        if self._task is None or self._task.done():
            async def _run():
                await self.bot.wait_until_ready()
                await self._loop()
            self._task = asyncio.create_task(_run(), name="stream-monitor")

    async def _loop(self):
        logger.info("🟢 StreamMonitor: polling begins — interval=60s")
        while True:
            try:
                await self._poll()
            except Exception as e:
                logger.error(f"🔴 StreamMonitor crash: {e}")
            await asyncio.sleep(60)

    async def _poll(self):
        twitch = self.app_state.twitch_api
        if not twitch: return

        rows = await self.db.fetch("SELECT twitch_login, guild_id, target_channel_id FROM streamers")
        if not rows: return

        logins = list(set([r["twitch_login"] for r in rows]))
        live_streams = await twitch.get_streams_by_logins(logins)
        live_map = {s["user_login"].lower(): s for s in live_streams}

        for row in rows:
            login = row["twitch_login"].lower()
            guild_id = row["guild_id"]
            channel_id = row["target_channel_id"]
            
            # Eğer yayıncıya özel kanal yoksa, varsayılan kanalı kullan
            if not channel_id:
                g_cfg = await self.db.fetchrow("SELECT announce_channel_id FROM guild_settings WHERE guild_id = $1", guild_id)
                channel_id = g_cfg["announce_channel_id"] if g_cfg else None

            if not channel_id: continue

            stream = live_map.get(login)
            state_key = (guild_id, login)
            prev = self._state.get(state_key, {})

            if stream:
                if not prev.get("live"):
                    await self._post_live(guild_id, channel_id, login, stream, state_key)
            elif prev.get("live"):
                await self._post_offline(guild_id, channel_id, login, prev, state_key)

    async def _post_live(self, guild_id, channel_id, login, stream, state_key):
        guild = self.bot.get_guild(guild_id)
        if not guild: return
        channel = guild.get_channel(channel_id) or await self.bot.fetch_channel(channel_id)
        if not channel: return

        user_info = await self.app_state.twitch_api.get_user_by_login(login)
        embed = build_live_embed(stream, user_info)
        
        live_role = discord.utils.get(guild.roles, name="Live")
        content = live_role.mention if live_role else None
        
        msg = await channel.send(content=content, embed=embed)
        self._state[state_key] = {"live": True, "message_id": msg.id}

    async def _post_offline(self, guild_id, channel_id, login, prev, state_key):
        guild = self.bot.get_guild(guild_id)
        if not guild: return
        channel = guild.get_channel(channel_id) or await self.bot.fetch_channel(channel_id)
        if channel and prev.get("message_id"):
            try:
                msg = await channel.fetch_message(prev["message_id"])
                await msg.edit(embed=build_offline_embed(login, login.capitalize()))
            except: pass
        self._state[state_key] = {"live": False}

# ==================================================
# REGISTER & COMMANDS
# ==================================================

async def register(bot, app_state, session):
    db = app_state.db
    monitor = StreamMonitor(bot, app_state)
    monitor.start()
    app_state.stream_monitor = monitor

    group = app_commands.Group(name="live", description="Manage Twitch live stream tracking")

    # --- FORCE POST (Admin Only) ---
    @group.command(name="force-post", description="⚠️ (Admin) Bir yayıncı için anında duyuru postu atar")
    @app_commands.describe(twitch_login="Duyurusu atılacak Twitch kullanıcı adı")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def force_post(interaction: discord.Interaction, twitch_login: str):
        await interaction.response.defer(ephemeral=True)
        login = twitch_login.lower().strip()
        
        twitch = app_state.twitch_api
        live_streams = await twitch.get_streams_by_logins([login])
        
        if not live_streams:
            return await interaction.followup.send(f"👩‍🔬 **{login}** şu an canlı yayında görünmüyor.")

        stream = live_streams[0]
        user_info = await twitch.get_user_by_login(login)
        
        row = await db.fetchrow("SELECT target_channel_id FROM streamers WHERE twitch_login = $1 AND guild_id = $2", login, interaction.guild_id)
        channel_id = row["target_channel_id"] if row else None
        
        if not channel_id:
            g_cfg = await db.fetchrow("SELECT announce_channel_id FROM guild_settings WHERE guild_id = $1", interaction.guild_id)
            channel_id = g_cfg["announce_channel_id"] if g_cfg else None

        if not channel_id:
            return await interaction.followup.send("❌ Duyuru kanalı ayarlanmamış.")

        try:
            channel = interaction.guild.get_channel(channel_id) or await bot.fetch_channel(channel_id)
            embed = build_live_embed(stream, user_info)
            live_role = discord.utils.get(interaction.guild.roles, name="Live")
            content = live_role.mention if live_role else None
            
            await channel.send(content=content, embed=embed)
            
            state_key = (interaction.guild_id, login)
            monitor._state[state_key] = {"live": True}
            
            await interaction.followup.send(f"✅ **{login}** için duyuru {channel.mention} kanalına anında gönderildi!")
        except Exception as e:
            await interaction.followup.send(f"❌ Hata: {e}")

    # --- ADD ---
    @group.command(name="add", description="Yayıncıyı listeye ve belirli kanala ekle")
    async def add(interaction: discord.Interaction, twitch_login: str, channel: discord.TextChannel = None):
        await interaction.response.defer(ephemeral=True)
        login = twitch_login.lower().strip()
        user = await app_state.twitch_api.get_user_by_login(login)
        if not user: return await interaction.followup.send("❌ Kullanıcı bulunamadı.")
        
        target_id = channel.id if channel else None
        await db.execute("""
            INSERT INTO streamers (twitch_user_id, twitch_login, guild_id, target_channel_id) 
            VALUES ($1, $2, $3, $4) 
            ON CONFLICT (twitch_login, guild_id) DO UPDATE SET target_channel_id = EXCLUDED.target_channel_id
        """, user["id"], login, interaction.guild_id, target_id)
        
        txt = f"**{channel.mention}**" if channel else "varsayılan"
        await interaction.followup.send(f"✅ **{user['display_name']}** artık {txt} kanalına duyurulacak.")

    # --- REMOVE ---
    @group.command(name="remove", description="Yayıncı takibini bırak")
    async def remove(interaction: discord.Interaction, twitch_login: str):
        await interaction.response.defer(ephemeral=True)
        await db.execute("DELETE FROM streamers WHERE twitch_login = $1 AND guild_id = $2", twitch_login.lower(), interaction.guild_id)
        await interaction.followup.send(f"✅ **{twitch_login}** kaldırıldı.")

    bot.tree.add_command(group)
