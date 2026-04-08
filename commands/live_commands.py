# commands/live_commands.py

import discord
from discord import app_commands
import logging
import asyncio
import time
from datetime import datetime, timezone

from core.event_bus import event_bus

logger = logging.getLogger("live-commands")


# ==================================================
# EMBED BUILDERS
# ==================================================

def build_live_embed(stream: dict, user: dict) -> discord.Embed:
    login      = stream.get("user_login") or user.get("login", "unknown")
    name       = stream.get("user_name")  or user.get("display_name", login)
    title      = stream.get("title", "") or ""
    game       = stream.get("game_name", "") or "Just Chatting"
    started_at = stream.get("started_at", "")
    stream_url = f"https://www.twitch.tv/{login}"

    if not game or game.lower() in ("unknown", "unknown game", ""):
        game = "Just Chatting"

    ts_str = "now"
    if started_at:
        try:
            dt     = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
            ts_str = f"<t:{int(dt.timestamp())}:R>"
        except Exception:
            pass

    # Title as description, Game + Started as inline fields
    embed = discord.Embed(
        url=stream_url,
        description=title if title else None,
        color=0xFFB6C1,  # baby pink
    )

    embed.set_author(
        name=name,
        url=stream_url,
        icon_url=user.get("profile_image_url"),
    )
    
    # Yedek olarak profil fotoğrafını sağ üste küçük thumbnail olarak ekleyelim
    profile_url = user.get("profile_image_url")
    if profile_url:
        embed.set_thumbnail(url=profile_url)

    embed.add_field(name="Game",    value=game,   inline=True)
    embed.add_field(name="Started", value=ts_str, inline=True)

    raw_thumb = stream.get("thumbnail_url", "")
    thumbnail = raw_thumb.replace("{width}", "1280").replace("{height}", "720")
    if thumbnail:
        embed.set_image(url=f"{thumbnail}?v={int(time.time())}")

    embed.set_footer(text="Vibes: Very Cool")
    embed.timestamp = discord.utils.utcnow()
    return embed

def build_offline_embed(
    login:        str,
    display_name: str,
    stream_info:  dict | None = None,
    vod_url:      str  | None = None,
    duration:     str  | None = None,
    user_info:    dict | None = None,
) -> discord.Embed:
    stream_url = f"https://twitch.tv/{login}"
    title_text = (stream_info.get("title") if stream_info else None) or ""
    game       = (stream_info.get("game_name") if stream_info else None) or "Just Chatting"

    embed = discord.Embed(
        description=f"*{title_text}*" if title_text else None,
        color=0x2f3136,
    )

    icon_url = user_info.get("profile_image_url") if user_info else None
    embed.set_author(
        name=f"{display_name} was live on Twitch",
        url=stream_url,
        icon_url=icon_url,
    )

    embed.add_field(name="🕹️ Game",  value=game,                                   inline=True)
    embed.add_field(name="Duration", value=duration or "Unknown",                  inline=True)
    embed.add_field(
        name="🖳 VOD",
        value=f"[Click to view]({vod_url})" if vod_url
              else f"[Videos](https://www.twitch.tv/{login}/videos)",
        inline=True,
    )

    embed.set_footer(text=f"Stream ended • twitch.tv/{login}")
    embed.timestamp = datetime.now(timezone.utc)
    return embed


# ==================================================
# LIVE ROLE HELPERS
# ==================================================

async def ensure_live_role(guild: discord.Guild) -> discord.Role | None:
    role = discord.utils.get(guild.roles, name="🟢 Live")
    if role:
        return role
    try:
        role = await guild.create_role(
            name="🟢 Live",
            color=discord.Color.green(),
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
    role = discord.utils.get(guild.roles, name="🟢 Live")
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
        logger.info(
            f"🟢 DEBUG StreamMonitor: Twitch says live → {list(live_map.keys()) or 'nobody'}"
        )

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
                logger.warning(
                    f"🟡 DEBUG StreamMonitor: {login} — no guild+channel found. "
                    f"guild_configs/guild_settings may be missing announce_channel_id"
                )
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
                    logger.warning(
                        f"🟡 DEBUG StreamMonitor: guild {guild_id} not in bot cache — "
                        f"bot may not be in this guild"
                    )
                    continue

                if stream:
                    new_title = stream.get("title", "")
                    new_game  = stream.get("game_name", "")
                    
                    if not prev.get("live"):
                        logger.info(
                            f"🚀 DEBUG StreamMonitor: {login} went LIVE — "
                            f"posting to channel {channel_id} in {guild.name}"
                        )
                        await self._post_live(guild, channel_id, login, stream, state_key)
                        
                    elif prev.get("title") != new_title or prev.get("game") != new_game:
                        if prev.get("title") != new_title and prev.get("game") != new_game:
                            change_type = "title+game"
                        elif prev.get("title") != new_title:
                            change_type = "title"
                        else:
                            change_type = "game"
                            
                        logger.info(
                            f"📡 DEBUG StreamMonitor: {login} {change_type} changed — updating"
                        )
                        await self._update_stream(
                            guild, channel_id, stream, prev, state_key, change_type
                        )
                    else:
                        # Eğer hiçbir şey değişmediyse ama son güncellemenin üzerinden 5 dakika (300 saniye) geçtiyse thumbnail'ı yakalamak için sessizce yenile
                        if time.time() - prev.get("last_updated", 0) > 300:
                            logger.info(f"🔄 DEBUG StreamMonitor: {login} hala canlı, thumbnail için sessiz yenileme yapılıyor")
                            await self._refresh_embed(guild, channel_id, stream, prev, state_key)
                        else:
                            logger.info(f"⚪ DEBUG StreamMonitor: {login} still live, no change")
                else:
                    if prev.get("live"):
                        logger.info(
                            f"⚫ DEBUG StreamMonitor: {login} went offline — posting"
                        )
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

            class WatchView(discord.ui.View):
                def __init__(self, url: str, streamer: str):
                    super().__init__(timeout=None)
                    self.add_item(discord.ui.Button(
                        label=f"Watch {streamer}",
                        style=discord.ButtonStyle.link,
                        url=url,
                    ))

            stream_url = f"https://www.twitch.tv/{login}"
            view = WatchView(stream_url, stream.get("user_name") or login)
            msg = await channel.send(content=content, embed=embed, view=view)

            self._state[state_key] = {
                "live":         True,
                "message_id":   msg.id,
                "channel_id":   channel_id,
                "title":        stream.get("title", ""),
                "game":         stream.get("game_name", ""),
                "started_at":   stream.get("started_at", ""),
                "last_updated": time.time(),
            }

            logger.info(f"{login} went live in {guild.name}")
            await assign_live_role(guild, login)

            try:
                await self.db.execute(
                    """
                    INSERT INTO stream_history (twitch_login, guild_id, title, game_name, started_at, peak_viewers)
                    VALUES ($1, $2, $3, $4, $5, $6)
                    """,
                    login, guild.id,
                    stream.get("title"), stream.get("game_name"),
                    datetime.now(timezone.utc),
                    stream.get("viewer_count", 0),
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
                lines.append(f"🎮 **Game:** ~~{prev.get('game', '?')}~~ → **{new_game}**")

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
            self._state[state_key]["last_updated"] = time.time()
            logger.info(f"📡 {login} stream updated ({change_type}) in {guild.name}")

        except Exception as e:
            logger.error(f"_update_stream failed for {login} in {guild.name}: {e}")

    async def _refresh_embed(self, guild, channel_id, stream, prev, state_key):
        """ Thumbnail gecikmesini telafi etmek için mesajı sessizce günceller. """
        login = stream.get("user_login", "")
        try:
            channel = guild.get_channel(channel_id) or await self.bot.fetch_channel(channel_id)
            if not channel:
                return

            if prev.get("message_id"):
                user_info = await self._get_user(login)
                msg = await channel.fetch_message(prev["message_id"])
                await msg.edit(embed=build_live_embed(stream, user_info))
                self._state[state_key]["last_updated"] = time.time()
                logger.info(f"🔄 DEBUG StreamMonitor: {login} embed sessizce yenilendi (Thumbnail kontrolü)")
        except discord.NotFound:
            self._state.pop(state_key, None)
        except Exception as e:
            logger.error(f"_refresh_embed failed for {login} in {guild.name}: {e}")

    async def _update_title(self, guild, channel_id, stream, prev, state_key, new_title):
        await self._update_stream(guild, channel_id, stream, prev, state_key, "title")

    async def _post_offline(self, guild, channel_id, login, prev, state_key):
        try:
            channel = guild.get_channel(channel_id) or await self.bot.fetch_channel(channel_id)

            stream_info = {
                "title":     prev.get("title", ""),
                "game_name": prev.get("game", ""),
            }
            duration  = None
            vod_url   = None
            user_info = None

            started_at = prev.get("started_at", "")
            if started_at:
                try:
                    start_dt = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
                    elapsed  = (datetime.now(timezone.utc) - start_dt).total_seconds()
                    h, rem   = divmod(int(elapsed), 3600)
                    m, s     = divmod(rem, 60)
                    duration = f"{h}h {m}m {s}s" if h else f"{m}m {s}s"
                except Exception:
                    pass

            try:
                api = self.app_state.twitch_api
                if api:
                    user_info = await api.get_user_by_login(login)
                    if user_info:
                        vod_data = await api.request(
                            "videos",
                            params={"user_id": user_info["id"], "type": "archive", "first": 1},
                        )
                        if vod_data and vod_data.get("data"):
                            vod = vod_data["data"][0]
                            vod_url = vod.get("url")
                            if not stream_info["title"] and vod.get("title"):
                                stream_info["title"] = vod["title"]
                            if not duration and vod.get("duration"):
                                import re as _re
                                parts = _re.findall(r'(\d+)([hms])', vod["duration"])
                                secs  = sum(int(v) * {"h":3600,"m":60,"s":1}[u] for v,u in parts)
                                h2, r = divmod(secs, 3600); m2, s2 = divmod(r, 60)
                                duration = f"{h2}h {m2}m {s2}s" if h2 else f"{m2}m {s2}s"
            except Exception as e:
                logger.warning(f"VOD fetch failed for {login}: {e}")

            offline_embed = build_offline_embed(
                login, login.capitalize(),
                stream_info=stream_info,
                vod_url=vod_url,
                duration=duration,
                user_info=user_info,
            )

            if channel and prev.get("message_id"):
                try:
                    msg = await channel.fetch_message(prev.get("message_id"))
                    await msg.edit(embed=offline_embed)
                except discord.NotFound:
                    if channel:
                        await channel.send(embed=offline_embed)
            elif channel:
                await channel.send(embed=offline_embed)

            self._state[state_key] = {"live": False}
            logger.info(f"{login} went offline in {guild.name}")

            try:
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
# HELPERS
# ==================================================

async def _get_announce_channel_id(db, guild_id: int) -> int | None:
    try:
        row = await db.fetchrow(
            """
            SELECT COALESCE(gs.announce_channel_id, gc.announce_channel_id)
                AS announce_channel_id
            FROM (SELECT $1::bigint AS guild_id) x
            LEFT JOIN guild_settings gs ON gs.guild_id = x.guild_id
            LEFT JOIN guild_configs  gc ON gc.guild_id = x.guild_id
            """,
            guild_id,
        )
        return row["announce_channel_id"] if row else None
    except Exception:
        return None


# ==================================================
# REGISTER
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

    @group.command(name="add", description="Track a Twitch streamer's live streams")
    @app_commands.describe(twitch_login="Twitch username to track (e.g. pokimane)")
    async def add_streamer(interaction: discord.Interaction, twitch_login: str):

        await interaction.response.defer(ephemeral=True)
        twitch_login = twitch_login.strip().lower()

        try:
            user = await app_state.twitch_api.get_user_by_login(twitch_login)
            if not user:
                return await interaction.followup.send(
                    f"❌ Twitch user **{twitch_login}** not found. Check the spelling.",
                )

            twitch_user_id = user["id"]
            display_name   = user.get("display_name", twitch_login)
            profile_image  = user.get("profile_image_url", "")

            existing = await db.fetchrow(
                "SELECT 1 FROM streamers WHERE twitch_login = $1 AND guild_id = $2",
                twitch_login, interaction.guild_id,
            )
            if existing:
                return await interaction.followup.send(
                    f"⚠️ **{display_name}** is already tracked in this server.",
                )

            await db.execute(
                """
                INSERT INTO streamers (twitch_user_id, twitch_login, guild_id)
                VALUES ($1, $2, $3) ON CONFLICT DO NOTHING
                """,
                twitch_user_id, twitch_login, interaction.guild_id,
            )

            await event_bus.emit("streamer_added", {
                "twitch_user_id": twitch_user_id,
                "twitch_login":   twitch_login,
                "guild_id":       interaction.guild_id,
            })

            live_streams = await app_state.twitch_api.get_streams_by_logins([twitch_login])
            is_live_now  = bool(live_streams)

            embed = discord.Embed(
                title="✅ Streamer Added",
                description=(
                    f"**{display_name}** is now tracked.\n"
                    + (
                        "🔴 **They're live right now!** Posting notification..."
                        if is_live_now else
                        "You'll get a notification when they go live."
                    )
                ),
                color=0x2ECC71,
            )
            if profile_image:
                embed.set_thumbnail(url=profile_image)
            embed.set_footer(text="Use /live list to see all tracked streamers")

            await interaction.followup.send(embed=embed)

            if is_live_now:
                stream = live_streams[0]
                channel_id = await _get_announce_channel_id(db, interaction.guild_id)
                if channel_id and monitor:
                    state_key = (interaction.guild_id, twitch_login)
                    await monitor._post_live(
                        interaction.guild,
                        channel_id,
                        twitch_login,
                        stream,
                        state_key,
                    )
                elif not channel_id:
                    await interaction.followup.send(
                        f"⚠️ **{display_name}** is live right now but no announce channel is set.\n"
                        f"Use `/live set-channel` to configure one, then I'll post notifications automatically.",
                        ephemeral=True,
                    )

        except Exception:
            logger.exception("add_streamer failed")
            await interaction.followup.send("❌ Something went wrong. Please try again.")

    @group.command(name="remove", description="Stop tracking a Twitch streamer")
    @app_commands.describe(twitch_login="Twitch username to stop tracking")
    async def remove_streamer(interaction: discord.Interaction, twitch_login: str):

        await interaction.response.defer(ephemeral=True)
        twitch_login = twitch_login.strip().lower()

        try:
            result = await db.execute(
                "DELETE FROM streamers WHERE twitch_login = $1 AND guild_id = $2",
                twitch_login, interaction.guild_id,
            )
            if result == "DELETE 0":
                return await interaction.followup.send(
                    f"❌ **{twitch_login}** isn't tracked in this server.",
                )

            await event_bus.emit("streamer_removed", {
                "twitch_login": twitch_login,
                "guild_id":     interaction.guild_id,
            })

            embed = discord.Embed(
                title="🗑️ Streamer Removed",
                description=f"**{twitch_login}** has been removed from tracking.",
                color=0xE74C3C,
            )
            await interaction.followup.send(embed=embed)

        except Exception:
            logger.exception("remove_streamer failed")
            await interaction.followup.send("❌ Something went wrong. Please try again.")

    @group.command(name="list", description="List all tracked streamers in this server")
    async def list_streamers(interaction: discord.Interaction):

        await interaction.response.defer(ephemeral=True)

        try:
            rows = await db.fetch(
                """
                SELECT twitch_login FROM streamers
                WHERE guild_id = $1 ORDER BY twitch_login ASC
                """,
                interaction.guild_id,
            )

            if not rows:
                return await interaction.followup.send(
                    "📭 No streamers tracked yet. Use `/live add` to add one!",
                )

            lines = [
                f"• [{r['twitch_login']}](https://www.twitch.tv/{r['twitch_login']})"
                for r in rows
            ]

            embed = discord.Embed(
                title=f"📡 Tracked Streamers — {interaction.guild.name}",
                description="\n".join(lines),
                color=0x9146FF,
            )
            count = len(rows)
            embed.set_footer(text=f"{count} streamer{'s' if count != 1 else ''} tracked")

            await interaction.followup.send(embed=embed)

        except Exception:
            logger.exception("list_streamers failed")
            await interaction.followup.send("❌ Something went wrong. Please try again.")

    @group.command(
        name="set-channel",
        description="Set the channel where live notifications are posted (admin only)",
    )
    @app_commands.describe(channel="The channel to post live notifications in")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def set_channel(
        interaction: discord.Interaction,
        channel: discord.TextChannel,
    ):
        await interaction.response.defer(ephemeral=True)

        try:
            await db.execute(
                """
                INSERT INTO guild_settings (guild_id, announce_channel_id)
                VALUES ($1, $2)
                ON CONFLICT (guild_id)
                DO UPDATE SET announce_channel_id = EXCLUDED.announce_channel_id
                """,
                interaction.guild_id,
                channel.id,
            )

            embed = discord.Embed(
                title="✅ Stream channel set",
                description=(
                    f"Live stream notifications will now be posted in {channel.mention}.\n\n"
                    f"Make sure the bot has **Send Messages** and **Embed Links** "
                    f"permissions in that channel."
                ),
                color=0x2ECC71,
            )
            embed.set_footer(text="Use /live set-games-channel to set the games channel")
            await interaction.followup.send(embed=embed)

        except Exception:
            logger.exception("set_channel failed")
            await interaction.followup.send("❌ Something went wrong. Please try again.")

    @set_channel.error
    async def set_channel_error(interaction: discord.Interaction, error):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message(
                "❌ You need the **Manage Server** permission to use this command.",
                ephemeral=True,
            )

    @group.command(
        name="set-games-channel",
        description="Set the channel for free game and deals posts (admin only)",
    )
    @app_commands.describe(channel="Channel to post free games and deals in")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def set_games_channel(
        interaction: discord.Interaction,
        channel: discord.TextChannel,
    ):
        await interaction.response.defer(ephemeral=True)

        try:
            await db.execute(
                """
                INSERT INTO guild_configs (guild_id, games_channel_id)
                VALUES ($1, $2)
                ON CONFLICT (guild_id) DO UPDATE
                SET games_channel_id = EXCLUDED.games_channel_id,
                    updated_at       = CURRENT_TIMESTAMP
                """,
                interaction.guild_id,
                channel.id,
            )

            embed = discord.Embed(
                title="✅ Games channel set",
                description=(
                    f"Free games, Steam deals and Prime Gaming posts will now "
                    f"appear in {channel.mention}.\n\n"
                    f"Stream live notifications will still go to your stream channel."
                ),
                color=0x2ECC71,
            )
            embed.set_footer(text="Use /live set-channel to change the stream channel")
            await interaction.followup.send(embed=embed)

        except Exception:
            logger.exception("set_games_channel failed")
            await interaction.followup.send(
                "❌ Something went wrong. Please try again.", ephemeral=True
            )

    @set_games_channel.error
    async def set_games_channel_error(interaction: discord.Interaction, error):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message(
                "❌ You need the **Manage Server** permission to use this command.",
                ephemeral=True,
            )

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
                        COALESCE(AVG(h.peak_viewers), 0) AS avg_viewers,
                        COALESCE(MAX(h.peak_viewers), 0) AS peak_viewers,
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
                return await interaction.followup.send(
                    "📭 No streamers tracked yet. Use `/live add` to add one!",
                )

            monitor  = getattr(app_state, "stream_monitor", None)
            live_now = set()
            if monitor and hasattr(monitor, "_state"):
                live_now = {
                    login for (_, login), st in monitor._state.items()
                    if st.get("live")
                }

            embed = discord.Embed(
                title=f"📊 Stream Stats — {interaction.guild.name}",
                color=0x9146FF,
            )

            for row in rows:
                login     = row["twitch_login"]
                url       = f"https://www.twitch.tv/{login}"
                indicator = "🔴 " if login in live_now else ""

                if has_history:
                    count        = int(row["stream_count"] or 0)
                    avg_viewers  = int(row["avg_viewers"] or 0)
                    peak_viewers = int(row["peak_viewers"] or 0)
                    total_secs   = int(row["total_secs"] or 0)
                    fav_game     = row["favourite_game"] or "—"
                    last_seen    = row["last_seen"]

                    total_h   = total_secs // 3600
                    total_m   = (total_secs % 3600) // 60
                    total_str = f"{total_h}h {total_m}m" if total_h else (f"{total_m}m" if total_m else "—")

                    last_str = "Never"
                    if last_seen:
                        try:
                            dt = last_seen if not isinstance(last_seen, str) else datetime.fromisoformat(last_seen)
                            last_str = f"<t:{int(dt.timestamp())}:R>"
                        except Exception:
                            pass

                    plural = 's' if count != 1 else ''
                    value = (
                        f"📺 **{count}** stream{plural}\n"
                        f"⏱️ **{total_str}** total\n"
                        f"👥 Avg **{avg_viewers:,}** · Peak **{peak_viewers:,}**\n"
                        f"🎮 **{fav_game}**\n"
                        f"🕐 {last_str}"
                    )
                else:
                    value = "💤 Stats build up after first stream."

                embed.add_field(
                    name=f"{indicator}[{login}]({url})",
                    value=value,
                    inline=True,
                )

            live_count = len(live_now & {r["twitch_login"] for r in rows})
            footer = f"🖥️ {len(rows)} tracked"
            if live_count:
                footer += f" · 🔴 {live_count} live now"
            if not has_history:
                footer += " · Stats build up over time"
            embed.set_footer(text=footer)
            embed.timestamp = discord.utils.utcnow()
            await interaction.followup.send(embed=embed)

        except Exception:
            logger.exception("live_stats failed")
            await interaction.followup.send("❌ Something went wrong. Please try again.")

    bot.tree.add_command(group)
    logger.info("live_commands registered")
