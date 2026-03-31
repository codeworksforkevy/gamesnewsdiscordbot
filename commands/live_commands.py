import discord
from discord import app_commands
import logging
import asyncio
import time
from datetime import datetime, timezone

logger = logging.getLogger("live-commands")

# ==================================================
# EMBED BUILDERS
# ==================================================

def build_live_embed(stream: dict, user: dict) -> discord.Embed:
    login = stream.get("user_login") or user.get("login", "unknown")
    name = stream.get("user_name") or user.get("display_name", login)
    stream_title = stream.get("title", "No Title")
    game_name = stream.get("game_name", "Creative / Art")
    
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

    # VIEWERS ÇIKARILDI - BAŞLIK (PROJECT) EKLENDİ
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
    embed.set_author(name=name, url=stream_url, icon_url=user.get("profile_image_url"))
    
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
            h, remainder = divmod(int(diff.total_seconds()), 3600)
            m, s = divmod(remainder, 60)
            duration_str = f"{h}h {m}m {s}s"
        except: pass

    embed = discord.Embed(
        title=f"{display_name} was live on Twitch",
        url=f"https://twitch.tv/{login}",
        description=f"*{prev_state.get('title', 'No title')}*", # ITALIC BAŞLIK
        color=0x2f3136, 
    )
    embed.add_field(name="👩‍💻 Game", value=prev_state.get("game", "Creative / Art"), inline=True)
    embed.add_field(name="⏱️ Duration", value=duration_str, inline=True)
    embed.add_field(name="🎬 VOD", value=f"[Click to watch](https://twitch.tv/{login}/videos)", inline=True)
    embed.set_footer(text=f"⚫ Stream ended • twitch.tv/{login}")
    embed.timestamp = now
    return embed

# ==================================================
# MONITOR & COMMANDS
# ==================================================

class StreamMonitor:
    def __init__(self, bot, app_state):
        self.bot = bot
        self.app_state = app_state
        self.db = app_state.db
        self._state = {}
        self._task = None

    def start(self):
        if self._task is None or self._task.done():
            async def _run():
                await self.bot.wait_until_ready()
                await self._loop()
            self._task = asyncio.create_task(_run(), name="stream-monitor")

    async def _loop(self):
        while True:
            try: await self._poll()
            except Exception as e: logger.error(f"Monitor error: {e}")
            await asyncio.sleep(60)

    async def _poll(self):
        twitch = self.app_state.twitch_api
        rows = await self.db.fetch("SELECT twitch_login, guild_id, target_channel_id FROM streamers")
        if not rows: return

        logins = list(set([r["twitch_login"] for r in rows]))
        live_streams = await twitch.get_streams_by_logins(logins)
        live_map = {s["user_login"].lower(): s for s in live_streams}

        for row in rows:
            login, guild_id, channel_id = row["twitch_login"].lower(), row["guild_id"], row["target_channel_id"]
            if not channel_id:
                g_cfg = await self.db.fetchrow("SELECT announce_channel_id FROM guild_settings WHERE guild_id = $1", guild_id)
                channel_id = g_cfg["announce_channel_id"] if g_cfg else None
            if not channel_id: continue

            stream = live_map.get(login)
            state_key = (guild_id, login)
            prev = self._state.get(state_key, {})

            if stream:
                if not prev.get("live"):
                    asyncio.create_task(self._delayed_post_live(guild_id, channel_id, login, stream, state_key))
                    self._state[state_key] = {"live": True, "pending": True}
                elif prev.get("title") != stream["title"] or prev.get("game") != stream.get("game_name"):
                    await self._update_stream(guild_id, channel_id, stream, prev, state_key)
            elif prev.get("live") and not prev.get("pending"):
                await self._post_offline(guild_id, channel_id, login, prev, state_key)

    async def _delayed_post_live(self, guild_id, channel_id, login, stream, state_key):
        await asyncio.sleep(15) 
        try:
            upd = await self.app_state.twitch_api.get_streams_by_logins([login])
            if upd: stream = upd[0]
        except: pass
        await self._post_live(guild_id, channel_id, login, stream, state_key)

    async def _post_live(self, guild_id, channel_id, login, stream, state_key):
        guild = self.bot.get_guild(guild_id)
        channel = guild.get_channel(channel_id) or await self.bot.fetch_channel(channel_id)
        if not channel: return
        user_info = await self.app_state.twitch_api.get_user_by_login(login)
        embed = build_live_embed(stream, user_info)
        live_role = discord.utils.get(guild.roles, name="Live")
        msg = await channel.send(content=live_role.mention if live_role else None, embed=embed)
        self._state[state_key] = {"live": True, "message_id": msg.id, "title": stream["title"], "game": stream.get("game_name"), "started_at": stream["started_at"]}

    async def _update_stream(self, guild_id, channel_id, stream, prev, state_key):
        guild = self.bot.get_guild(guild_id)
        channel = guild.get_channel(channel_id) or await self.bot.fetch_channel(channel_id)
        if not channel or not prev.get("message_id"): return
        user_info = await self.app_state.twitch_api.get_user_by_login(stream["user_login"])
        try:
            msg = await channel.fetch_message(prev["message_id"])
            await msg.edit(embed=build_live_embed(stream, user_info))
            self._state[state_key].update({"title": stream["title"], "game": stream.get("game_name")})
        except: pass

    async def _post_offline(self, guild_id, channel_id, login, prev, state_key):
        guild = self.bot.get_guild(guild_id)
        channel = guild.get_channel(channel_id) or await self.bot.fetch_channel(channel_id)
        if channel and prev.get("message_id"):
            try:
                msg = await channel.fetch_message(prev["message_id"])
                await msg.edit(embed=build_offline_embed(login, login.capitalize(), prev))
            except: pass
        self._state[state_key] = {"live": False}

async def register(bot, app_state, session):
    monitor = StreamMonitor(bot, app_state)
    monitor.start()
    group = app_commands.Group(name="live", description="Twitch tracking")

    @group.command(name="force-post", description="⚠️ Send instant announcement")
    async def force_post(interaction: discord.Interaction, twitch_login: str):
        await interaction.response.defer(ephemeral=True)
        login = twitch_login.lower().strip()
        live_streams = await app_state.twitch_api.get_streams_by_logins([login])
        if not live_streams: return await interaction.followup.send(f"👩‍🔬 **{login}** is not live.")
        stream, user_info = live_streams[0], await app_state.twitch_api.get_user_by_login(login)
        row = await app_state.db.fetchrow("SELECT target_channel_id FROM streamers WHERE twitch_login = $1 AND guild_id = $2", login, interaction.guild_id)
        ch_id = row["target_channel_id"] if row else (await app_state.db.fetchrow("SELECT announce_channel_id FROM guild_settings WHERE guild_id = $1", interaction.guild_id))["announce_channel_id"]
        channel = interaction.guild.get_channel(ch_id) or await bot.fetch_channel(ch_id)
        await channel.send(embed=build_live_embed(stream, user_info))
        await interaction.followup.send("✅ Forced post sent!")

    @group.command(name="add", description="Add streamer")
    async def add(interaction: discord.Interaction, twitch_login: str, channel: discord.TextChannel = None):
        await interaction.response.defer(ephemeral=True)
        user = await app_state.twitch_api.get_user_by_login(twitch_login.lower())
        if not user: return await interaction.followup.send("❌ Not found.")
        await app_state.db.execute("INSERT INTO streamers (twitch_user_id, twitch_login, guild_id, target_channel_id) VALUES ($1, $2, $3, $4) ON CONFLICT (twitch_login, guild_id) DO UPDATE SET target_channel_id = EXCLUDED.target_channel_id", user["id"], twitch_login.lower(), interaction.guild_id, channel.id if channel else None)
        await interaction.followup.send(f"✅ **{user['display_name']}** added.")

    bot.tree.add_command(group)
