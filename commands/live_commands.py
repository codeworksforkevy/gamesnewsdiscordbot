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
    game       = stream.get("game_name", "Unknown game")
    started_at = stream.get("started_at", "")
    stream_url = f"https://www.twitch.tv/{login}"

    started_str = ""
    if started_at:
        try:
            dt = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
            ts = int(dt.timestamp())
            started_str = f"\n☕ Live since <t:{ts}:R>"
        except Exception:
            pass

    raw_thumb = stream.get("thumbnail_url", "")
    thumbnail = raw_thumb.replace("{width}", "1280").replace("{height}", "720")

    embed = discord.Embed(
        title=title,
        url=stream_url,
        description=(
            f"**{name}** is live on Twitch!\n\n"
            f"👩‍💻 **{game}**"
            f"{started_str}"
        ),
        color=0x9146FF,
    )

    embed.set_author(
        name=f"{name} is live!",
        url=stream_url,
        icon_url=user.get("profile_image_url"),
    )

    if thumbnail:
        embed.set_image(url=thumbnail)

    embed.set_footer(text="🟣 Live on Twitch")
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
            # Buradaki asyncio.create_task'ı botun hazır olduğunu bekleyecek şekilde sarmalıyoruz
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
        msg = await channel.send(embed=embed)
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
        await interaction.followup.send(f"📡 **Tracked Streamers:**\n{txt}")

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
