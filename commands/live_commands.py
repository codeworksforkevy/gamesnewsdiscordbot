# commands/live_commands.py
#
# Features:
#   - /live add    → add any number of streamers
#   - /live remove → remove a streamer
#   - /live list   → see all tracked streamers
#   - Rich "now live" embed with thumbnail, title, game, viewer count
#   - Automatic title update if streamer changes their stream title
#   - "Live" Discord role automatically assigned when streamer goes live
#     and removed when they go offline
#   - Unlimited streamers per server

import discord
from discord import app_commands
import logging
import asyncio

from core.event_bus import event_bus

logger = logging.getLogger("live-commands")

# ==================================================
# HELPERS
# ==================================================

def build_live_embed(stream: dict, user: dict) -> discord.Embed:
    """
    Build the rich 'now live' embed shown in the announce channel.

    stream dict keys (from Twitch API):
        title, game_name, viewer_count, thumbnail_url, user_login, user_name

    user dict keys (from Twitch API):
        profile_image_url, login
    """
    login      = stream.get("user_login") or user.get("login", "unknown")
    name       = stream.get("user_name") or user.get("display_name", login)
    title      = stream.get("title", "Untitled stream")
    game       = stream.get("game_name", "Unknown game")
    viewers    = stream.get("viewer_count", 0)
    stream_url = f"https://www.twitch.tv/{login}"

    # Twitch thumbnail URL needs width/height substituted
    raw_thumb = stream.get("thumbnail_url", "")
    thumbnail = raw_thumb.replace("{width}", "1280").replace("{height}", "720")

    embed = discord.Embed(
        title=title,
        url=stream_url,
        description=(
            f"**{name}** is live on Twitch!\n\n"
            f"🎮 **{game}**\n"
            f"👀 **{viewers:,}** viewers"
        ),
        color=0x9146FF,   # Twitch purple
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
    """Simple embed shown when a tracked streamer goes offline."""
    embed = discord.Embed(
        title=f"{display_name} is now offline",
        color=0x808080,
    )
    embed.set_footer(text="⚫ Stream ended")
    return embed


# ==================================================
# LIVE ROLE HELPER
# ==================================================

async def ensure_live_role(guild: discord.Guild) -> discord.Role | None:
    """
    Returns the 'Live' role, creating it if it doesn't exist.
    Returns None if the bot lacks permission to manage roles.
    """
    role = discord.utils.get(guild.roles, name="Live")
    if role:
        return role
    try:
        role = await guild.create_role(
            name="Live",
            color=discord.Color.from_rgb(145, 70, 255),  # Twitch purple
            mentionable=True,
            reason="Auto-created by Find a Curie bot for live tracking",
        )
        logger.info(f"Created 'Live' role in {guild.name}")
        return role
    except discord.Forbidden:
        logger.warning(f"No permission to create 'Live' role in {guild.name}")
        return None
    except Exception as e:
        logger.error(f"Failed to create 'Live' role in {guild.name}: {e}")
        return None


async def assign_live_role(guild: discord.Guild, twitch_login: str) -> None:
    """
    Assign the 'Live' role to any guild member whose username matches
    the Twitch login. Also works if their Discord nickname matches.
    """
    role = await ensure_live_role(guild)
    if not role:
        return

    login_lower = twitch_login.lower()

    for member in guild.members:
        names_to_check = [
            member.name.lower(),
            (member.nick or "").lower(),
            (member.global_name or "").lower(),
        ]
        if login_lower in names_to_check:
            try:
                if role not in member.roles:
                    await member.add_roles(role, reason="Streamer went live")
                    logger.info(f"Assigned Live role to {member} in {guild.name}")
            except discord.Forbidden:
                logger.warning(f"No permission to assign role to {member}")
            except Exception as e:
                logger.error(f"Role assign error for {member}: {e}")


async def remove_live_role(guild: discord.Guild, twitch_login: str) -> None:
    """Remove the 'Live' role from the matching guild member."""
    role = discord.utils.get(guild.roles, name="Live")
    if not role:
        return

    login_lower = twitch_login.lower()

    for member in guild.members:
        names_to_check = [
            member.name.lower(),
            (member.nick or "").lower(),
            (member.global_name or "").lower(),
        ]
        if login_lower in names_to_check and role in member.roles:
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
    Handles:
      - New stream detected  → post embed, assign Live role
      - Title changed        → edit existing embed automatically
      - Stream ended         → edit embed to offline, remove Live role
    """

    def __init__(self, bot, app_state):
        self.bot       = bot
        self.app_state = app_state
        self.db        = app_state.db
        # Tracks current state per streamer per guild
        # Key: (guild_id, twitch_login)
        # Value: {"message_id": int, "channel_id": int, "title": str, "live": bool}
        self._state: dict = {}
        self._task  = None

    def start(self):
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._loop())
            logger.info("StreamMonitor started")

    def stop(self):
        if self._task:
            self._task.cancel()

    async def _loop(self):
        # Wait for bot to be fully ready before polling
        await self.bot.wait_until_ready()
        logger.info("StreamMonitor: bot ready, polling begins")

        while True:
            try:
                await self._poll()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.exception(f"StreamMonitor poll error: {e}")
            await asyncio.sleep(60)   # poll every 60 seconds

    async def _poll(self):
        twitch = self.app_state.twitch_api

        # Fetch all tracked streamers across all guilds
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

        # Batch fetch live stream data from Twitch
        try:
            live_streams = await twitch.get_streams_by_logins(logins)
        except Exception as e:
            logger.error(f"Twitch streams fetch failed: {e}")
            return

        # Dict of login → stream data (only currently live streamers)
        live_map = {s["user_login"].lower(): s for s in live_streams}

        # Process each streamer per guild
        for row in rows:
            login = row["twitch_login"].lower()

            # Find all guilds tracking this streamer
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
                guild_id    = guild_row["guild_id"]
                channel_id  = guild_row["announce_channel_id"]
                state_key   = (guild_id, login)
                prev        = self._state.get(state_key, {})

                guild = self.bot.get_guild(guild_id)
                if not guild:
                    continue

                if stream:
                    # ── Streamer is LIVE ───────────────────────────────────
                    new_title = stream.get("title", "")

                    if not prev.get("live"):
                        # First time going live → post embed
                        await self._post_live(
                            guild, channel_id, login, stream, state_key
                        )
                    elif prev.get("title") != new_title:
                        # Already live but title changed → edit embed
                        await self._update_title(
                            guild, channel_id, stream, prev, state_key, new_title
                        )
                else:
                    # ── Streamer is OFFLINE ────────────────────────────────
                    if prev.get("live"):
                        await self._post_offline(
                            guild, channel_id, login, prev, state_key
                        )

    async def _get_user_info(self, login: str) -> dict:
        """Fetch Twitch user profile (for avatar + display name)."""
        try:
            return await self.app_state.twitch_api.get_user_by_login(login) or {}
        except Exception:
            return {}

    async def _post_live(
        self,
        guild: discord.Guild,
        channel_id: int,
        login: str,
        stream: dict,
        state_key: tuple,
    ):
        """Post a new 'now live' embed and assign the Live role."""
        try:
            channel = guild.get_channel(channel_id) or await self.bot.fetch_channel(channel_id)
            if not channel:
                return

            user_info = await self._get_user_info(login)
            embed     = build_live_embed(stream, user_info)

            # Mention @Live role in the message so members get notified
            live_role = await ensure_live_role(guild)
            content   = live_role.mention if live_role else None

            msg = await channel.send(content=content, embed=embed)

            self._state[state_key] = {
                "live":       True,
                "message_id": msg.id,
                "channel_id": channel_id,
                "title":      stream.get("title", ""),
            }

            logger.info(f"{login} went live in guild {guild.name}")

            # Assign Live role to matching Discord member
            await assign_live_role(guild, login)

        except Exception as e:
            logger.error(f"Failed to post live embed for {login} in {guild.name}: {e}")

    async def _update_title(
        self,
        guild: discord.Guild,
        channel_id: int,
        stream: dict,
        prev: dict,
        state_key: tuple,
        new_title: str,
    ):
        """Edit the existing embed when the stream title changes."""
        try:
            channel = guild.get_channel(channel_id) or await self.bot.fetch_channel(channel_id)
            if not channel:
                return

            msg = await channel.fetch_message(prev["message_id"])
            if not msg:
                return

            login     = stream.get("user_login", "")
            user_info = await self._get_user_info(login)
            new_embed = build_live_embed(stream, user_info)

            await msg.edit(embed=new_embed)

            self._state[state_key]["title"] = new_title
            logger.info(f"{login} updated stream title in {guild.name}: {new_title!r}")

        except discord.NotFound:
            # Message was deleted — clear state so it reposts next poll
            self._state.pop(state_key, None)
        except Exception as e:
            logger.error(f"Failed to update embed for {guild.name}: {e}")

    async def _post_offline(
        self,
        guild: discord.Guild,
        channel_id: int,
        login: str,
        prev: dict,
        state_key: tuple,
    ):
        """Edit the live embed to show offline status and remove Live role."""
        try:
            channel = guild.get_channel(channel_id) or await self.bot.fetch_channel(channel_id)
            if channel and prev.get("message_id"):
                try:
                    msg = await channel.fetch_message(prev["message_id"])
                    display = stream_display_name(login)
                    await msg.edit(embed=build_offline_embed(login, display))
                except discord.NotFound:
                    pass   # message already deleted, that's fine

            self._state[state_key] = {"live": False}
            logger.info(f"{login} went offline in guild {guild.name}")

        except Exception as e:
            logger.error(f"Failed to post offline embed for {login} in {guild.name}: {e}")

        # Always try to remove the Live role even if embed edit fails
        await remove_live_role(guild, login)


def stream_display_name(login: str) -> str:
    """Capitalise login as a best-effort display name when full data isn't available."""
    return login.capitalize()


# ==================================================
# REGISTER
# ==================================================

async def register(bot, app_state, session):

    db = app_state.db

    # Start the background stream monitor
    monitor = StreamMonitor(bot, app_state)
    monitor.start()

    # Store on app_state so other parts of the bot can reference it
    app_state.stream_monitor = monitor

    # ── Slash command group ────────────────────────────────────────────────
    group = app_commands.Group(
        name="live",
        description="Manage Twitch live stream tracking"
    )

    # ==================================================
    # /live add
    # ==================================================
    @group.command(name="add", description="Track a Twitch streamer's live streams")
    @app_commands.describe(twitch_login="The Twitch username to track (e.g. xqc)")
    async def add_streamer(interaction: discord.Interaction, twitch_login: str):

        await interaction.response.defer(ephemeral=True)

        twitch_login = twitch_login.strip().lower()

        try:
            twitch_api = app_state.twitch_api
            user = await twitch_api.get_user_by_login(twitch_login)

            if not user:
                return await interaction.followup.send(
                    f"❌ Twitch user **{twitch_login}** not found. Check the spelling.",
                    ephemeral=True,
                )

            twitch_user_id   = user["id"]
            display_name     = user.get("display_name", twitch_login)
            profile_image    = user.get("profile_image_url")

            # Check if already tracked in this guild
            existing = await db.fetchrow(
                """
                SELECT 1 FROM streamers
                WHERE twitch_login = $1 AND guild_id = $2
                """,
                twitch_login,
                interaction.guild_id,
            )

            if existing:
                return await interaction.followup.send(
                    f"⚠️ **{display_name}** is already being tracked in this server.",
                    ephemeral=True,
                )

            await db.execute(
                """
                INSERT INTO streamers (twitch_user_id, twitch_login, guild_id)
                VALUES ($1, $2, $3)
                ON CONFLICT DO NOTHING
                """,
                twitch_user_id,
                twitch_login,
                interaction.guild_id,
            )

            await event_bus.emit("streamer_added", {
                "twitch_user_id": twitch_user_id,
                "twitch_login":   twitch_login,
                "guild_id":       interaction.guild_id,
            })

            embed = discord.Embed(
                title="✅ Streamer Added",
                description=(
                    f"**{display_name}** is now tracked.\n"
                    f"You'll get a notification in this server when they go live."
                ),
                color=0x2ECC71,
            )
            if profile_image:
                embed.set_thumbnail(url=profile_image)

            embed.set_footer(text=f"Use /live list to see all tracked streamers")

            await interaction.followup.send(embed=embed)

        except Exception:
            logger.exception("Add streamer failed")
            await interaction.followup.send(
                "❌ Something went wrong. Please try again.",
                ephemeral=True,
            )

    # ==================================================
    # /live remove
    # ==================================================
    @group.command(name="remove", description="Stop tracking a Twitch streamer")
    @app_commands.describe(twitch_login="The Twitch username to stop tracking")
    async def remove_streamer(interaction: discord.Interaction, twitch_login: str):

        await interaction.response.defer(ephemeral=True)

        twitch_login = twitch_login.strip().lower()

        try:
            result = await db.execute(
                """
                DELETE FROM streamers
                WHERE twitch_login = $1 AND guild_id = $2
                """,
                twitch_login,
                interaction.guild_id,
            )

            if result == "DELETE 0":
                return await interaction.followup.send(
                    f"❌ **{twitch_login}** isn't being tracked in this server.",
                    ephemeral=True,
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
            logger.exception("Remove streamer failed")
            await interaction.followup.send(
                "❌ Something went wrong. Please try again.",
                ephemeral=True,
            )

    # ==================================================
    # /live list
    # ==================================================
    @group.command(name="list", description="List all tracked streamers in this server")
    async def list_streamers(interaction: discord.Interaction):

        await interaction.response.defer(ephemeral=True)

        try:
            rows = await db.fetch(
                """
                SELECT twitch_login, twitch_user_id
                FROM streamers
                WHERE guild_id = $1
                ORDER BY twitch_login ASC
                """,
                interaction.guild_id,
            )

            if not rows:
                return await interaction.followup.send(
                    "📭 No streamers are being tracked yet.\n"
                    "Use `/live add` to add one!",
                    ephemeral=True,
                )

            lines = []
            for r in rows:
                login = r["twitch_login"]
                url   = f"https://www.twitch.tv/{login}"
                lines.append(f"• [{login}]({url})")

            embed = discord.Embed(
                title=f"📡 Tracked Streamers — {interaction.guild.name}",
                description="\n".join(lines),
                color=0x9146FF,
            )
            embed.set_footer(
                text=f"{len(rows)} streamer{'s' if len(rows) != 1 else ''} tracked"
            )

            await interaction.followup.send(embed=embed)

        except Exception:
            logger.exception("List streamers failed")
            await interaction.followup.send(
                "❌ Something went wrong. Please try again.",
                ephemeral=True,
            )

    # ── Register group ─────────────────────────────────────────────────────
    bot.tree.add_command(group)
    logger.info("live_commands registered")
