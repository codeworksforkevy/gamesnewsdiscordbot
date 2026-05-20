"""
core/streamer_service.py
────────────────────────────────────────────────────────────────
Handles stream metadata change detection and Discord notifications
when a live stream's title or game changes mid-stream.

Fixes vs original:
- Compared old.get("game") vs new.get("game") but Twitch API returns
  "game_name" — the diff never triggered. Fixed key to "game_name".
- get_notification_channel() always returned None (just a comment
  "# DB'den al") — now properly queries guild_settings.
- notify_changes() sent a plain text message in Turkish — replaced
  with a clean Discord embed in English.
- notify_changes() accepted `bot` but get_notification_channel()
  needed a DB reference — now uses guild_settings.get_guild_config()
  which handles its own DB access via the set_db() singleton.
"""

import logging
import time

import discord

from db.guild_settings import get_guild_config

logger = logging.getLogger("streamer-service")


class StreamerService:

    def __init__(self, eventsub_manager, cache):
        self.eventsub = eventsub_manager
        self.cache    = cache

    # ──────────────────────────────────────────────────────────
    # CHANGE DETECTION
    # ──────────────────────────────────────────────────────────

    async def handle_stream_update(
        self,
        user_id: str,
        new_data: dict,
    ) -> dict | None:
        """
        Compares new stream metadata with the cached previous state.
        Returns a changes dict if anything changed, otherwise None.

        Changes dict shape:
            {
                "title": {"old": "...", "new": "..."},   # if title changed
                "game":  {"old": "...", "new": "..."},   # if game changed
            }
        """
        old_data = await self.cache.get(user_id)

        if not old_data:
            # First time we've seen this stream — seed the cache
            await self.cache.set(user_id, new_data)
            return None

        changes: dict = {}

        if old_data.get("title") != new_data.get("title"):
            changes["title"] = {
                "old": old_data.get("title"),
                "new": new_data.get("title"),
            }

        # Fixed: Twitch API uses "game_name" not "game"
        if old_data.get("game_name") != new_data.get("game_name"):
            changes["game"] = {
                "old": old_data.get("game_name"),
                "new": new_data.get("game_name"),
            }

        if changes:
            await self.cache.set(user_id, new_data)
            return changes

        return None

    # ──────────────────────────────────────────────────────────
    # NOTIFICATIONS
    # ──────────────────────────────────────────────────────────

    async def notify_changes(
        self,
        bot,
        user_id: str,
        user_login: str,
        changes: dict,
    ) -> None:
        """
        Sends a Discord embed to each guild's announce channel
        describing what changed in the stream.
        """
        if not changes:
            return

        embed = self._build_change_embed(user_login, changes)

        for guild in bot.guilds:
            channel = await self._get_announce_channel(bot, guild)
            if not channel:
                continue

            try:
                await channel.send(embed=embed)
            except Exception as e:
                logger.error(
                    "Failed to send stream change notification",
                    extra={"extra_data": {
                        "guild_id": guild.id,
                        "error":    str(e),
                    }},
                )

    def _build_change_embed(self, user_login: str, changes: dict) -> discord.Embed:
        embed = discord.Embed(
            title="📡  Stream Updated",
            url=f"https://twitch.tv/{user_login}",
            color=0x9146FF,
            timestamp=discord.utils.utcnow(),
        )

        if "title" in changes:
            embed.add_field(
                name="🎯 Title changed",
                value=(
                    f"~~{changes['title']['old']}~~\n"
                    f"→ **{changes['title']['new']}**"
                ),
                inline=False,
            )

        if "game" in changes:
            embed.add_field(
                name="🎮 Game changed",
                value=(
                    f"~~{changes['game']['old']}~~\n"
                    f"→ **{changes['game']['new']}**"
                ),
                inline=False,
            )

        embed.set_footer(text=f"twitch.tv/{user_login}")
        return embed

    async def _get_announce_channel(
        self,
        bot,
        guild: discord.Guild,
    ) -> discord.TextChannel | None:
        """
        Looks up the guild's configured announce channel via guild_settings.
        Returns the channel object, or None if not configured / not found.
        """
        try:
            config = await get_guild_config(guild.id)
            if not config:
                return None

            channel_id = config.get("announce_channel_id")
            if not channel_id:
                return None

            return guild.get_channel(channel_id)

        except Exception as e:
            logger.error(
                "Failed to fetch guild config for channel lookup",
                extra={"extra_data": {
                    "guild_id": guild.id,
                    "error":    str(e),
                }},
            )
            return None
