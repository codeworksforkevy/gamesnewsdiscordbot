# commands/live_commands.py

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
        logger.info(f"Created Live role in {guild.name}")
        return role
    except discord.Forbidden:
        logger.warning(f"No permission to create Live role in {guild.name}")
        return None
    except Exception as e:
        logger.error(f"Live role creation error in {guild.name}: {e}")
        return None


async def assign_live_role(guild: discord.Guild, twitch_login: str) -> None:
    role = await ensure_live_role(guild)
    if not role:
        return
    login_lower = twitch_login.lower()
    for member in guild.members:
        checks = [
            member.name.lower(),
            (member.nick or "").lower(),
            (member.global_name or "").lower(),
        ]
        if login_lower in checks and role not in member.roles:
            try:
                await member.add_roles(role, reason="Streamer went live")
                logger.info(f"Assigned Live role to {member} in {guild.name}")
            except discord.Forbidden:
                logger.warning(f"No permission to assign role to {member}")
            except Exception as e:
                logger.error(f"Role assign error for {member}: {e}")


async def remove_live_role(guild: discord.Guild, twitch_login: str) -> None:
    role = discord.utils.get(guild.roles, name="Live")
    if not role:
        return
    login_lower = twitch_login.lower()
    for member in guild.members:
        checks = [
            member.name.lower(),
            (member.nick or "").lower(),
            (member.global_name or "").lower(),
        ]
        if login_lower in checks and role in member.roles:
            try:
                await member.remove_roles(role, reason="Stream ended")
                logger.info(f"Removed Live role from {member} in {guild.name}")
            except discord.Forbidden:
                logger.warning(f"No permission to remove role from {member}")
            except Exception as e:
                logger.error(f"Role remove error for {member}: {e}")


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
            self._task = asyncio.create_task(self._loop(), name="stream-monitor")
            logger.info("StreamMonitor started")

    def stop(self):
        if self._task:
            self._task.cancel()

    async def _loop(self):
        await self.bot.wait_until_ready()
        logger.info("🟢 StreamMonitor: polling begins — interval=60s")
        cycle = 0
        while True:
            cycle += 1
            logger.info(f"🔄 StreamMonitor: cycle #{cycle} starting")
            try:
                await self._poll()
            except asyncio.CancelledError:
                logger.info("StreamMonitor: cancelled")
                break
            except Exception as e:
                logger.exception(f"🔴 StreamMonitor: cycle #{cycle} crashed — {e}")
            logger.info(f"🔄 StreamMonitor: cycle #{cycle} done — sleeping 60s")
            await asyncio.sleep(60)

    async def _poll(self):
        twitch = self.app_state.twitch_api

        if not twitch:
            logger.error("🔴 DEBUG StreamMonitor: twitch_api is None — cannot poll")
            return

        try:
            rows = await self.db.fetch(
                "SELECT DISTINCT twitch_login, twitch_user_id FROM streamers"
            )
        except Exception as e:
            logger.error(f"🔴 DEBUG StreamMonitor: DB fetch failed — {e}")
            return

        if not rows:
            logger.info("🟡 DEBUG StreamMonitor: no streamers in DB — nothing to poll")
            return

        logins = [r["twitch_login"] for r in rows]
        logger.info(
            f"🟢 DEBUG StreamMonitor: polling {len(logins)} streamers — {logins}"
        )

        try:
            live_streams = await twitch.get_streams_by_logins(logins)
        except Exception as e:
            logger.error(f"🔴 DEBUG StreamMonitor: Twitch API failed — {e}")
            return

        live_map = {s["user_login"].lower(): s for s in live_streams}

        for row in rows:
            login = row["twitch_login"].lower()

            try:
                guild_rows = await self.db.fetch(
                    """
                    SELECT s.guild_id,
                        COALESCE(gs.announce_channel_id, gc.announce_channel_id)
                            AS announce_channel_id
                    FROM streamers s
                    LEFT JOIN guild_settings gs ON gs.guild_id = s.guild_id
                    LEFT JOIN guild_configs  gc ON gc.guild_id = s.guild_id
                    WHERE s.twitch_login = $1
                      AND COALESCE(gs.announce_channel_id, gc.announce_channel_id)
                          IS NOT NULL
                    """,
                    login,
                )
            except Exception as e:
                logger.error(f"🔴 DEBUG StreamMonitor: guild fetch failed for {login} — {e}")
                continue

            if not guild_rows:
                continue

            stream    = live_map.get(login)
            prev_state = self._state.get((guild_rows[0]["guild_id"], login), {})

            for guild_row in guild_rows:
                guild_id   = guild_row["guild_id"]
                channel_id = guild_row["announce_channel_id"]
                state_key  = (guild_id, login)
                prev       = self._state.get(state_key, {})
                guild      = self.bot.get_guild(guild_id)

                if not guild:
                    continue

                if stream:
                    new_title = stream.get("title", "")
                    new_game  = stream.get("game_name", "")
                    if not prev.get("live"):
                        await self._post_live(guild, channel_id, login, stream, state_key)
                    elif prev.get("title") != new_title or prev.get("game") != new_game:
                        change_type = "title+game" if (prev.get("title") != new_title and prev.get("game") != new_game) \
                                      else ("title" if prev.get("title") != new_title else "game")
                        await self._update_stream(
                            guild, channel_id, stream, prev, state_key, change_type
                        )
                else:
                    if prev.get("live"):
                        await self._post_offline(guild, channel_id, login, prev, state_key)

    async def _get_user(self, login: str) -> dict:
        try:
            return await self.app_state.twitch_api.get_user_by_login(login) or {}
        except Exception:
            return {}

    async def _post_live(self, guild, channel_id, login, stream, state_key):
        try:
            channel = guild.get_channel(channel_id) or await self.bot.fetch_channel(channel_id)
            if not channel:
                return

            user_info = await self._get_user(login)
            embed     = build_live_embed(stream, user_info)
            live_role = await ensure_live_role(guild)
            content   = live_role.mention if live_role else None

            msg = await channel.send(content=content, embed=embed)

            self._state[state_key] = {
                "live":        True,
                "message_id": msg.id,
                "channel_id": channel_id,
                "title":      stream.get("title", ""),
                "game":       stream.get("game_name", ""),
                "started_at": stream.get("started_at", ""),
            }

            logger.info(f"{login} went live in {guild.name}")
            await assign_live_role(guild, login)

            # Record stream start in history (peak_viewers kaldırıldı/varsayılan 0)
            try:
                from datetime import datetime, timezone
                await self.db.execute(
                    """
                    INSERT INTO stream_history (twitch_login, guild_id, title, game_name, started_at, peak_viewers)
                    VALUES ($1, $2, $3, $4, $5, $6)
                    """,
                    login, guild.id,
                    stream.get("title"), stream.get("game_name"),
                    datetime.now(timezone.utc),
                    0,
                )
            except Exception:
                pass 

        except Exception as e:
            logger.error(f"post_live failed for {login} in {guild.name}: {e}")

    async def _update_stream(self, guild, channel_id, stream, prev, state_key, change_type):
        login     = stream.get("user_login", "")
        new_title = stream.get("title", "")
        new_game  = stream.get("game_name", "")
        try:
            channel = guild.get_channel(channel_id) or await self.bot.fetch_channel(channel_id)
            if not channel:
                return

            if prev.get("message_id"):
                try:
                    user_info = await self._get_user(login)
                    msg = await channel.fetch_message(prev["message_id"])
                    await msg.edit(embed=build_live_embed(stream, user_info))
                except discord.NotFound:
                    self._state.pop(state_key, None)

            lines = []
            if change_type in ("title", "title+game"):
                lines.append(f"📝 **Title:** ~~{prev.get('title', '?')}~~ → **{new_title}**")
            if change_type in ("game", "title+game"):
                lines.append(f"👩‍💻 **Game:** ~~{prev.get('game', '?')}~~ → **{new_game}**")

            update_embed = discord.Embed(
                title="📡 Stream Updated",
                description="\n".join(lines),
                url=f"https://twitch.tv/{login}",
                color=0xF5A623,
            )
            update_embed.set_footer(text=f"twitch.tv/{login}")
            update_embed.timestamp = discord.utils.utcnow()
            await channel.send(embed=update_embed)

            self._state[state_key]["title"] = new_title
            self._state[state_key]["game"]  = new_game
            logger.info(f"📡 {login} stream updated ({change_type}) in {guild.name}")

        except Exception as e:
            logger.error(f"_update_stream failed for {login} in {guild.name}: {e}")

    async def _post_offline(self, guild, channel_id, login, prev, state_key):
        try:
            channel = guild.get_channel(channel_id) or await self.bot.fetch_channel(channel_id)
            if channel and prev.get("message_id"):
                try:
                    msg = await channel.fetch_message(prev["message_id"])
                    await msg.edit(embed=build_offline_embed(login, login.capitalize()))
                except discord.NotFound:
                    pass
            self._state[state_key] = {"live": False}
            logger.info(f"{login} went offline in {guild.name}")

            try:
                from datetime import datetime, timezone
                now = datetime.now(timezone.utc)
                started_at = prev.get("started_at")
                duration = 0
                if started_at:
                    try:
                        start_dt = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
                        duration = int((now - start_dt).total_seconds())
                    except Exception:
                        pass
                await self.db.execute(
                    """
                    UPDATE stream_history SET ended_at=$1, duration_secs=$2
                    WHERE twitch_login=$3 AND guild_id=$4 AND ended_at IS NULL
                    """,
                    now, duration, login, guild.id,
                )
            except Exception:
                pass 

        except Exception as e:
            logger.error(f"post_offline failed for {login} in {guild.name}: {e}")
        await remove_live_role(guild, login)


# ==================================================
# REGISTER & COMMANDS
# ==================================================

async def register(bot, app_state, session):
    db = app_state.db
    monitor = StreamMonitor(bot, app_state)
    monitor.start()
    app_state.stream_monitor = monitor

    group = app_commands.Group(
        name="live",
        description="Manage Twitch live stream tracking",
    )

    # ... [add, remove, list, set-channel kodları değişmedi, sadece stats güncellendi] ...

    @group.command(name="stats", description="📊 Detailed stream stats for tracked streamers")
    async def live_stats(interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            try:
                rows = await db.fetch(
                    """
                    SELECT
                        s.twitch_login,
                        COUNT(h.id)                       AS stream_count,
                        COALESCE(SUM(h.duration_secs), 0) AS total_secs,
                        MAX(h.started_at)                 AS last_seen,
                        (
                            SELECT h2.game_name FROM stream_history h2
                            WHERE h2.twitch_login = s.twitch_login
                              AND h2.guild_id = s.guild_id
                              AND h2.game_name IS NOT NULL
                            GROUP BY h2.game_name
                            ORDER BY COUNT(*) DESC LIMIT 1
                        ) AS favourite_game
                    FROM streamers s
                    LEFT JOIN stream_history h
                        ON h.twitch_login = s.twitch_login
                        AND h.guild_id = s.guild_id
                    WHERE s.guild_id = $1
                    GROUP BY s.twitch_login
                    ORDER BY stream_count DESC, s.twitch_login ASC
                    """,
                    interaction.guild_id,
                )
                has_history = True
            except Exception:
                rows = await db.fetch(
                    "SELECT twitch_login FROM streamers WHERE guild_id = $1",
                    interaction.guild_id,
                )
                has_history = False

            if not rows:
                return await interaction.followup.send("📭 No streamers tracked yet.")

            monitor  = getattr(app_state, "stream_monitor", None)
            live_now = {login for (_, login), st in monitor._state.items() if st.get("live")} if monitor else set()

            embed = discord.Embed(title=f"📊 Stream Stats — {interaction.guild.name}", color=0x9146FF)

            for row in rows:
                login     = row["twitch_login"]
                indicator = "🔴 " if login in live_now else ""
                
                if has_history:
                    count      = int(row["stream_count"] or 0)
                    total_secs = int(row["total_secs"] or 0)
                    fav_game   = row["favourite_game"] or "—"
                    last_seen  = row["last_seen"]

                    total_h = total_secs // 3600
                    total_m = (total_secs % 3600) // 60
                    total_str = f"{total_h}h {total_m}m" if total_h else (f"{total_m}m" if total_m else "—")

                    last_str = "Never"
                    if last_seen:
                        try:
                            dt = last_seen if not isinstance(last_seen, str) else datetime.fromisoformat(last_seen)
                            last_str = f"<t:{int(dt.timestamp())}:R>"
                        except Exception: pass

                    value = (
                        f"📺 **{count}** streams\n"
                        f"☕ **{total_str}** total\n"
                        f"👩‍💻 **{fav_game}**\n"
                        f"📅 {last_str}"
                    )
                else:
                    value = "💤 Stats build up after first stream."

                embed.add_field(name=f"{indicator}[{login}](https://twitch.tv/{login})", value=value, inline=True)

            embed.set_footer(text=f"🖥️ {len(rows)} tracked")
            await interaction.followup.send(embed=embed)
        except Exception:
            logger.exception("live_stats failed")
            await interaction.followup.send("❌ Error fetching stats.")

    # ... [Kalan register işlemleri] ...
    bot.tree.add_command(group)
