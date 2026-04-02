"""
cogs/live_role_cog.py
────────────────────────────────────────────────────────────────
Manages a "🟢 Live" Discord role that is automatically:
  - Created in each guild if it doesn't already exist
  - Assigned to a member when their linked Twitch stream goes live
  - Removed when the stream ends

The role is HOISTED (shows separately in the member list) and
coloured Twitch purple so it's immediately visible.

HOW MEMBER ↔ STREAMER MATCHING WORKS
──────────────────────────────────────
Priority order (first match wins):
  1. DB lookup: streamers table has a discord_user_id column → direct match
  2. Nickname fallback: member's server nickname contains the Twitch login

For best results, add a discord_user_id column to your streamers table:
  ALTER TABLE streamers ADD COLUMN discord_user_id BIGINT;

SETUP
─────
In main.py / bot startup:
    await bot.load_extension("cogs.live_role_cog")

Then wire event_bus in your startup after bot is ready:
    from core.event_bus import event_bus
    from cogs.live_role_cog import LiveRoleCog

    cog = bot.cogs.get("LiveRoleCog")
    if cog:
        event_bus.subscribe("stream_online",  cog.on_stream_online)
        event_bus.subscribe("stream_offline", cog.on_stream_offline)
"""

import logging

import discord
from discord.ext import commands

from db.guild_settings import get_guild_config

logger = logging.getLogger("live-role-cog")

# Role appearance
ROLE_NAME  = "🟢 Live"
ROLE_COLOR = discord.Color.green()     # Green — matches 🟢 emoji
ROLE_HOIST = True                       # Show separately in member list


# ──────────────────────────────────────────────────────────────
# COG
# ──────────────────────────────────────────────────────────────

class LiveRoleCog(commands.Cog):

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ──────────────────────────────────────────────────────────
    # ROLE MANAGEMENT
    # ──────────────────────────────────────────────────────────

    async def _get_or_create_live_role(self, guild: discord.Guild) -> discord.Role | None:
        """
        Returns the Live role for the guild, creating it if absent.
        Falls back to the guild config's live_role_id if set there.
        """
        # 1. Check guild config for a custom live role
        config = await get_guild_config(guild.id)
        if config and config.get("live_role_id"):
            role = guild.get_role(config["live_role_id"])
            if role:
                return role

        # 2. Look for existing role by name
        existing = discord.utils.get(guild.roles, name=ROLE_NAME)
        if existing:
            return existing

        # 3. Create it
        try:
            role = await guild.create_role(
                name=ROLE_NAME,
                color=ROLE_COLOR,
                hoist=ROLE_HOIST,
                mentionable=False,
                reason="Auto-created by bot for live stream notifications",
            )
            logger.info(
                "Live role created",
                extra={"extra_data": {
                    "guild_id":   guild.id,
                    "guild_name": guild.name,
                    "role_id":    role.id,
                }},
            )
            return role

        except discord.Forbidden:
            logger.error(
                "Missing permissions to create Live role",
                extra={"extra_data": {"guild_id": guild.id}},
            )
            return None

        except Exception as e:
            logger.error(
                "Failed to create Live role",
                extra={"extra_data": {"guild_id": guild.id, "error": str(e)}},
            )
            return None

    # ──────────────────────────────────────────────────────────
    # MEMBER MATCHING
    # ──────────────────────────────────────────────────────────

    async def _find_members(
        self,
        guild: discord.Guild,
        user_login: str,
        discord_user_id: int | None = None,
    ) -> list[discord.Member]:
        """
        Finds the Discord member(s) that correspond to a Twitch login.
        Returns a list (usually 0 or 1 members).
        """
        # Direct match via discord_user_id (most reliable)
        if discord_user_id:
            member = guild.get_member(discord_user_id)
            if member:
                return [member]

        # Nickname fallback — member's nick contains the Twitch login
        matched = []
        for member in guild.members:
            if member.bot:
                continue
            display = (member.nick or "").lower()
            if user_login in display:
                matched.append(member)

        return matched

    # ──────────────────────────────────────────────────────────
    # EVENT HANDLERS  (subscribed via event_bus)
    # ──────────────────────────────────────────────────────────

    async def on_stream_online(self, payload: dict) -> None:
        """Called by event_bus when a stream goes live."""
        user_login       = payload.get("broadcaster_user_login", "").lower()
        discord_user_id  = payload.get("discord_user_id")   # optional DB field

        for guild in self.bot.guilds:
            role = await self._get_or_create_live_role(guild)
            if not role:
                continue

            members = await self._find_members(guild, user_login, discord_user_id)

            for member in members:
                if role in member.roles:
                    continue   # already has it

                try:
                    await member.add_roles(role, reason=f"Stream live: {user_login}")
                    logger.info(
                        "Live role assigned",
                        extra={"extra_data": {
                            "guild_id":  guild.id,
                            "member":    str(member),
                            "streamer":  user_login,
                        }},
                    )
                except discord.Forbidden:
                    logger.error(
                        "No permission to assign Live role",
                        extra={"extra_data": {
                            "guild_id": guild.id,
                            "member":   str(member),
                        }},
                    )
                except Exception as e:
                    logger.error(
                        "Failed to assign Live role",
                        extra={"extra_data": {
                            "guild_id": guild.id,
                            "member":   str(member),
                            "error":    str(e),
                        }},
                    )

    async def on_stream_offline(self, payload: dict) -> None:
        """Called by event_bus when a stream ends."""
        user_login      = payload.get("broadcaster_user_login", "").lower()
        discord_user_id = payload.get("discord_user_id")

        for guild in self.bot.guilds:

            # Don't create the role just to remove it — if it doesn't exist
            # there's nothing to remove
            role = discord.utils.get(guild.roles, name=ROLE_NAME)
            if not role:
                config = await get_guild_config(guild.id)
                if config and config.get("live_role_id"):
                    role = guild.get_role(config["live_role_id"])
            if not role:
                continue

            members = await self._find_members(guild, user_login, discord_user_id)

            for member in members:
                if role not in member.roles:
                    continue   # already removed

                try:
                    await member.remove_roles(role, reason=f"Stream ended: {user_login}")
                    logger.info(
                        "Live role removed",
                        extra={"extra_data": {
                            "guild_id": guild.id,
                            "member":   str(member),
                            "streamer": user_login,
                        }},
                    )
                except discord.Forbidden:
                    logger.error(
                        "No permission to remove Live role",
                        extra={"extra_data": {
                            "guild_id": guild.id,
                            "member":   str(member),
                        }},
                    )
                except Exception as e:
                    logger.error(
                        "Failed to remove Live role",
                        extra={"extra_data": {
                            "guild_id": guild.id,
                            "member":   str(member),
                            "error":    str(e),
                        }},
                    )

    # ──────────────────────────────────────────────────────────
    # STARTUP: ensure role exists in all guilds
    # ──────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        """Pre-creates the Live role in every guild on startup."""
        for guild in self.bot.guilds:
            try:
                await self._get_or_create_live_role(guild)
            except Exception as e:
                logger.error(
                    f"Live role setup failed for {guild.name}: {e}",
                    extra={"extra_data": {"guild_id": guild.id, "error": str(e)}},
                )

    @commands.Cog.listener()
    async def on_guild_join(self, guild: discord.Guild) -> None:
        """Creates the Live role when the bot joins a new guild."""
        try:
            await self._get_or_create_live_role(guild)
        except Exception as e:
            logger.error(
                f"Live role setup failed on guild join {guild.name}: {e}",
                extra={"extra_data": {"guild_id": guild.id, "error": str(e)}},
            )


# ──────────────────────────────────────────────────────────────
# SETUP HOOK
# ──────────────────────────────────────────────────────────────

async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(LiveRoleCog(bot))
    logger.info("LiveRoleCog loaded")
