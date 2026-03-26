# commands/live_commands.py
#
# UX features in this file:
#   1. /live add      — "Already live" instant alert if streamer is live right now
#   2. /live add      — Confirmation embed with profile picture
#   3. /live remove   — Clean removal with confirmation
#   4. /live list     — Clickable Twitch links + streamer count
#   5. /live set-channel — Admins set announce channel via slash command
#   6. /live stats    — Stream activity summary per streamer
#   7. StreamMonitor  — Rich embed: thumbnail, title, game, viewer count,
#                       "live for X" relative timestamp (auto-updates in Discord)
#   8. StreamMonitor  — Auto-edits embed when stream title changes
#   9. StreamMonitor  — Live role assigned on stream start, removed on end

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
    """
    Rich 'now live' embed.
    UX: started_at uses Discord's <t:X:R> format — shows "started 2 hours ago"
        and updates live in Discord without any bot action.
    """
    login      = stream.get("user_login") or user.get("login", "unknown")
    name       = stream.get("user_name")  or user.get("display_name", login)
    title      = stream.get("title", "Untitled stream")
    game       = stream.get("game_name", "Unknown game")
    viewers    = stream.get("viewer_count", 0)
    started_at = stream.get("started_at", "")
    stream_url = f"https://www.twitch.tv/{login}"

    # Build "live for X" timestamp
    started_str = ""
    if started_at:
        try:
            dt = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
            ts = int(dt.timestamp())
            started_str = f"\n🕐 Live since <t:{ts}:R>"
        except Exception:
            pass

    # Substitute Twitch thumbnail dimensions
    raw_thumb = stream.get("thumbnail_url", "")
    thumbnail = raw_thumb.replace("{width}", "1280").replace("{height}", "720")

    embed = discord.Embed(
        title=title,
        url=stream_url,
        description=(
            f"**{name}** is live on Twitch!\n\n"
            f"🎮 **{game}**\n"
            f"👀 **{viewers:,}** viewers"
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
# FREE GAMES CLAIM BUTTON VIEW
# UX: attached to free game embeds so users can click
#     directly to the store page
# ==================================================

class ClaimButton(discord.ui.View):
    """Single 'Claim now' button linking to a store URL."""

    def __init__(self, url: str, label: str = "🎮 Claim now"):
        super().__init__(timeout=None)   # persistent — never expires
        self.add_item(
            discord.ui.Button(
                label=label,
                url=url,
                style=discord.ButtonStyle.link,
            )
        )


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
    """
    Polls Twitch every 60 seconds for all tracked streamers.
    One batch API call covers all streamers — no per-streamer requests.

    State per (guild_id, login):
        live       : bool
        message_id : int   — Discord message to edit on title change / offline
        channel_id : int
        title      : str   — last known title, used to detect changes
    """

    def __init__(self, bot, app_state):
        self.bot       = bot
        self.app_state = app_state
        self.db        = app_state.db
        self._state: dict[tuple, dict] = {}
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
        logger.info("StreamMonitor: polling begins")
        while True:
            try:
                await self._poll()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.exception(f"StreamMonitor poll error: {e}")
            await asyncio.sleep(60)

    async def _poll(self):
        twitch = self.app_state.twitch_api

        try:
            rows = await self.db.fetch(
                "SELECT DISTINCT twitch_login, twitch_user_id FROM streamers"
            )
        except Exception as e:
            logger.error(f"StreamMonitor DB fetch failed: {e}")
            return

        if not rows:
            return

        logins = [r["twitch_login"] for r in rows]

        try:
            live_streams = await twitch.get_streams_by_logins(logins)
        except Exception as e:
            logger.error(f"Twitch batch fetch failed: {e}")
            return

        live_map = {s["user_login"].lower(): s for s in live_streams}

        for row in rows:
            login = row["twitch_login"].lower()

            try:
                guild_rows = await self.db.fetch(
                    """
                    SELECT s.guild_id, gs.announce_channel_id
                    FROM streamers s
                    JOIN guild_settings gs ON gs.guild_id = s.guild_id
                    WHERE s.twitch_login = $1
                    """,
                    login,
                )
            except Exception as e:
                logger.error(f"Guild fetch failed for {login}: {e}")
                continue

            stream = live_map.get(login)

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
                    if not prev.get("live"):
                        await self._post_live(guild, channel_id, login, stream, state_key)
                    elif prev.get("title") != new_title:
                        await self._update_title(guild, channel_id, stream, prev, state_key, new_title)
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

            user_info  = await self._get_user(login)
            embed      = build_live_embed(stream, user_info)
            live_role  = await ensure_live_role(guild)
            content    = live_role.mention if live_role else None

            msg = await channel.send(content=content, embed=embed)

            self._state[state_key] = {
                "live":       True,
                "message_id": msg.id,
                "channel_id": channel_id,
                "title":      stream.get("title", ""),
            }

            logger.info(f"{login} went live in {guild.name}")
            await assign_live_role(guild, login)

        except Exception as e:
            logger.error(f"post_live failed for {login} in {guild.name}: {e}")

    async def _update_title(self, guild, channel_id, stream, prev, state_key, new_title):
        try:
            channel = guild.get_channel(channel_id) or await self.bot.fetch_channel(channel_id)
            if not channel:
                return
            msg = await channel.fetch_message(prev["message_id"])
            user_info = await self._get_user(stream.get("user_login", ""))
            await msg.edit(embed=build_live_embed(stream, user_info))
            self._state[state_key]["title"] = new_title
            logger.info(f"{login} updated title in {guild.name}: {new_title!r}")
        except discord.NotFound:
            self._state.pop(state_key, None)
        except Exception as e:
            logger.error(f"update_title failed in {guild.name}: {e}")

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
        except Exception as e:
            logger.error(f"post_offline failed for {login} in {guild.name}: {e}")
        await remove_live_role(guild, login)


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

    # ── /live add ──────────────────────────────────────────────────────────
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

            # ── UX: "Already live" instant alert ──────────────────────────
            # Check if the streamer is live RIGHT NOW so the mod doesn't
            # have to wait up to 60s for the next monitor poll.
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

            # If they're live now, fire the notification immediately
            if is_live_now and monitor:
                stream    = live_streams[0]
                state_key = (interaction.guild_id, twitch_login)
                await monitor._post_live(
                    interaction.guild,
                    await _get_announce_channel_id(db, interaction.guild_id),
                    twitch_login,
                    stream,
                    state_key,
                )

        except Exception:
            logger.exception("add_streamer failed")
            await interaction.followup.send("❌ Something went wrong. Please try again.")

    # ── /live remove ───────────────────────────────────────────────────────
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

    # ── /live list ─────────────────────────────────────────────────────────
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

            # UX: clickable Twitch links
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

    # ── /live set-channel ──────────────────────────────────────────────────
    # UX: admins set the announce channel via slash command —
    #     no database editing needed.
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
                title="✅ Announce channel set",
                description=(
                    f"Live stream notifications will now be posted in {channel.mention}.\n\n"
                    f"Make sure the bot has **Send Messages** and **Embed Links** "
                    f"permissions in that channel."
                ),
                color=0x2ECC71,
            )
            embed.set_footer(text="Use /live add to start tracking streamers")
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

    # ── /live stats ────────────────────────────────────────────────────────
    # UX: shows stream activity summary for all tracked streamers.
    # Reads from a stream_history table (see note below).
    @group.command(name="stats", description="View stream activity for tracked streamers")
    async def live_stats(interaction: discord.Interaction):

        await interaction.response.defer(ephemeral=True)

        try:
            # Try to fetch from stream_history table
            # If the table doesn't exist yet, falls back to basic streamer list
            try:
                rows = await db.fetch(
                    """
                    SELECT
                        s.twitch_login,
                        COUNT(h.id)            AS stream_count,
                        AVG(h.peak_viewers)    AS avg_viewers,
                        MAX(h.started_at)      AS last_seen
                    FROM streamers s
                    LEFT JOIN stream_history h
                        ON h.twitch_login = s.twitch_login
                        AND h.guild_id    = s.guild_id
                    WHERE s.guild_id = $1
                    GROUP BY s.twitch_login
                    ORDER BY stream_count DESC, s.twitch_login ASC
                    """,
                    interaction.guild_id,
                )
                has_history = True
            except Exception:
                # stream_history table doesn't exist yet — show basic list
                rows = await db.fetch(
                    "SELECT twitch_login FROM streamers WHERE guild_id = $1",
                    interaction.guild_id,
                )
                has_history = False

            if not rows:
                return await interaction.followup.send(
                    "📭 No streamers are being tracked yet. Use `/live add` to add one!",
                )

            embed = discord.Embed(
                title=f"📊 Stream Stats — {interaction.guild.name}",
                color=0x9146FF,
            )

            for row in rows:
                login = row["twitch_login"]
                url   = f"https://www.twitch.tv/{login}"

                if has_history:
                    count       = row["stream_count"] or 0
                    avg_viewers = int(row["avg_viewers"] or 0)
                    last_seen   = row["last_seen"]

                    last_str = "Never"
                    if last_seen:
                        try:
                            if isinstance(last_seen, str):
                                dt = datetime.fromisoformat(last_seen)
                            else:
                                dt = last_seen
                            ts       = int(dt.timestamp())
                            last_str = f"<t:{ts}:R>"
                        except Exception:
                            pass

                    value = (
                        f"📺 **{count}** stream{'s' if count != 1 else ''} tracked\n"
                        f"👀 Avg **{avg_viewers:,}** viewers\n"
                        f"🕐 Last seen {last_str}"
                    )
                else:
                    value = "No history yet — stats build up over time."

                embed.add_field(
                    name=f"[{login}]({url})",
                    value=value,
                    inline=True,
                )

            if not has_history:
                embed.set_footer(
                    text="Full stats will appear once the stream_history table is set up."
                )

            await interaction.followup.send(embed=embed)

        except Exception:
            logger.exception("live_stats failed")
            await interaction.followup.send("❌ Something went wrong. Please try again.")

    # ── Register group ─────────────────────────────────────────────────────
    bot.tree.add_command(group)
    logger.info("live_commands registered")


# ==================================================
# HELPERS
# ==================================================

async def _get_announce_channel_id(db, guild_id: int) -> int | None:
    """Fetch the announce channel ID for a guild from the DB."""
    try:
        row = await db.fetchrow(
            "SELECT announce_channel_id FROM guild_settings WHERE guild_id = $1",
            guild_id,
        )
        return row["announce_channel_id"] if row else None
    except Exception:
        return None
