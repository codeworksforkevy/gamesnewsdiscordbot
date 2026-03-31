import discord
from discord import app_commands
import logging
import asyncio
from datetime import datetime, timezone

from core.event_bus import event_bus

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

    # Zaman damgası
    ts_str = "nu / now"
    if started_at:
        try:
            dt = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
            ts = int(dt.timestamp())
            ts_str = f"<t:{ts}:R>"
        except:
            pass

    # İstediğin özel açıklama metni ve emoji düzeni
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
        color=0xFFB6C1, # Samimi ve yumuşak bir pembe tonu
    )

    # Author sadece streamer adı
    embed.set_author(
        name=name,
        url=stream_url,
        icon_url=user.get("profile_image_url"),
    )

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
# LIVE ROLE HELPERS
# ==================================================

async def ensure_live_role(guild: discord.Guild) -> discord.Role | None:
    role = discord.utils.get(guild.roles, name="Live")
    if role:
        return role
    try:
        role = await guild.create_role(
            name="Live",
            color=discord.Color.from_rgb(145, 70, 255),
            mentionable=True,
            reason="Auto-created by Find a Curie bot",
        )
        return role
    except Exception as e:
        logger.error(f"Live role creation error: {e}")
        return None


async def assign_live_role(guild: discord.Guild, twitch_login: str) -> None:
    role = await ensure_live_role(guild)
    if not role: return
    login_lower = twitch_login.lower()
    for member in guild.members:
        checks = [member.name.lower(), (member.nick or "").lower(), (member.global_name or "").lower()]
        if login_lower in checks and role not in member.roles:
            try: await member.add_roles(role)
            except: pass


async def remove_live_role(guild: discord.Guild, twitch_login: str) -> None:
    role = discord.utils.get(guild.roles, name="Live")
    if not role: return
    login_lower = twitch_login.lower()
    for member in guild.members:
        checks = [member.name.lower(), (member.nick or "").lower(), (member.global_name or "").lower()]
        if login_lower in checks and role in member.roles:
            try: await member.remove_roles(role)
            except: pass


# ==================================================
# STREAM MONITOR
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

        rows = await self.db.fetch("SELECT DISTINCT twitch_login FROM streamers")
        if not rows: return

        logins = [r["twitch_login"] for r in rows]
        live_streams = await twitch.get_streams_by_logins(logins)
        live_map = {s["user_login"].lower(): s for s in live_streams}

        for row in rows:
            login = row["twitch_login"].lower()
            # Kanal bilgisini çekiyoruz (guild_settings öncelikli)
            guild_rows = await self.db.fetch("""
                SELECT s.guild_id, COALESCE(gs.announce_channel_id, gc.announce_channel_id) AS announce_channel_id
                FROM streamers s
                LEFT JOIN guild_settings gs ON gs.guild_id = s.guild_id
                LEFT JOIN guild_configs gc ON gc.guild_id = s.guild_id
                WHERE s.twitch_login = $1 AND COALESCE(gs.announce_channel_id, gc.announce_channel_id) IS NOT NULL
            """, login)

            stream = live_map.get(login)
            for g_row in guild_rows:
                state_key = (g_row["guild_id"], login)
                prev = self._state.get(state_key, {})
                guild = self.bot.get_guild(g_row["guild_id"])
                if not guild: continue

                if stream:
                    if not prev.get("live"):
                        await self._post_live(guild, g_row["announce_channel_id"], login, stream, state_key)
                    elif prev.get("title") != stream["title"] or prev.get("game") != stream["game_name"]:
                        await self._update_stream(guild, g_row["announce_channel_id"], stream, prev, state_key)
                elif prev.get("live"):
                    await self._post_offline(guild, g_row["announce_channel_id"], login, prev, state_key)

    async def _post_live(self, guild, channel_id, login, stream, state_key):
        channel = guild.get_channel(channel_id) or await self.bot.fetch_channel(channel_id)
        if not channel: return
        user_info = await self.app_state.twitch_api.get_user_by_login(login)
        embed = build_live_embed(stream, user_info)
        
        # Etiketleme için rol kontrolü
        live_role = discord.utils.get(guild.roles, name="Live")
        content = live_role.mention if live_role else None
        
        msg = await channel.send(content=content, embed=embed)
        self._state[state_key] = {"live": True, "message_id": msg.id, "title": stream["title"], "game": stream["game_name"], "started_at": stream["started_at"]}
        await assign_live_role(guild, login)

    async def _update_stream(self, guild, channel_id, stream, prev, state_key):
        channel = guild.get_channel(channel_id) or await self.bot.fetch_channel(channel_id)
        if not channel: return
        user_info = await self.app_state.twitch_api.get_user_by_login(stream["user_login"])
        try:
            msg = await channel.fetch_message(prev["message_id"])
            await msg.edit(embed=build_live_embed(stream, user_info))
        except: pass
        self._state[state_key].update({"title": stream["title"], "game": stream["game_name"]})

    async def _post_offline(self, guild, channel_id, login, prev, state_key):
        channel = guild.get_channel(channel_id) or await self.bot.fetch_channel(channel_id)
        if channel and prev.get("message_id"):
            try:
                msg = await channel.fetch_message(prev["message_id"])
                await msg.edit(embed=build_offline_embed(login, login.capitalize()))
            except: pass
        self._state[state_key] = {"live": False}
        await remove_live_role(guild, login)

# ==================================================
# REGISTER & COMMANDS
# ==================================================

async def register(bot, app_state, session):
    db = app_state.db
    monitor = StreamMonitor(bot, app_state)
    monitor.start()
    app_state.stream_monitor = monitor

    group = app_commands.Group(name="live", description="Manage Twitch live stream tracking")

    # --- ADD ---
    @group.command(name="add", description="Track a Twitch streamer")
    async def add(interaction: discord.Interaction, twitch_login: str):
        await interaction.response.defer(ephemeral=True)
        login = twitch_login.lower().strip()
        user = await app_state.twitch_api.get_user_by_login(login)
        if not user: return await interaction.followup.send("❌ User not found.")
        
        await db.execute("INSERT INTO streamers (twitch_user_id, twitch_login, guild_id) VALUES ($1, $2, $3) ON CONFLICT DO NOTHING",
                        user["id"], login, interaction.guild_id)
        await interaction.followup.send(f"✅ Now tracking **{user['display_name']}**")

    # --- REMOVE ---
    @group.command(name="remove", description="Stop tracking a streamer")
    async def remove(interaction: discord.Interaction, twitch_login: str):
        await interaction.response.defer(ephemeral=True)
        await db.execute("DELETE FROM streamers WHERE twitch_login = $1 AND guild_id = $2", twitch_login.lower(), interaction.guild_id)
        await interaction.followup.send(f"✅ Removed **{twitch_login}**")

    # --- LIST ---
    @group.command(name="list", description="List tracked streamers")
    async def list_cmd(interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        rows = await db.fetch("SELECT twitch_login FROM streamers WHERE guild_id = $1", interaction.guild_id)
        if not rows: return await interaction.followup.send("📭 No streamers tracked.")
        txt = "\n".join([f"• {r['twitch_login']}" for r in rows])
        await interaction.followup.send(f"👩‍🔬 **Tracked Streamers:**\n{txt}")

    # --- SET CHANNEL (Özel Kanal Belirleme) ---
    @group.command(name="set-channel", description="Yayın duyurularının yapılacağı kanalı belirle")
    @app_commands.describe(channel="Duyuruların gönderileceği metin kanalı")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def set_channel(interaction: discord.Interaction, channel: discord.TextChannel):
        await interaction.response.defer(ephemeral=True)
        try:
            await db.execute("""
                INSERT INTO guild_settings (guild_id, announce_channel_id)
                VALUES ($1, $2)
                ON CONFLICT (guild_id) DO UPDATE SET announce_channel_id = EXCLUDED.announce_channel_id
            """, interaction.guild_id, channel.id)
            await interaction.followup.send(f"✅ Yayın duyuruları artık {channel.mention} kanalına gönderilecek.")
        except Exception as e:
            logger.error(f"Set channel error: {e}")
            await interaction.followup.send("❌ Kanal ayarlanırken bir hata oluştu.")

    # --- STATS ---
    @group.command(name="stats", description="📊 Stream stats")
    async def stats(interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        rows = await db.fetch("""
            SELECT s.twitch_login, COUNT(h.id) as count, COALESCE(SUM(h.duration_secs), 0) as secs
            FROM streamers s
            LEFT JOIN stream_history h ON h.twitch_login = s.twitch_login AND h.guild_id = s.guild_id
            WHERE s.guild_id = $1 GROUP BY s.twitch_login
        """, interaction.guild_id)
        
        if not rows: return await interaction.followup.send("📭 No data yet.")
        embed = discord.Embed(title="📊 Stream Stats", color=0x9146FF)
        for r in rows:
            h, m = divmod(r["secs"] // 60, 60)
            embed.add_field(name=r["twitch_login"], value=f"📺 {r['count']} streams\n⏱️ {int(h)}h {int(m)}m total", inline=True)
        await interaction.followup.send(embed=embed)

    bot.tree.add_command(group)
