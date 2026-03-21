import discord
from discord import app_commands
import logging

from services.streamer_registry import add_streamer, remove_streamer
from services.guild_config import upsert_guild_config

logger = logging.getLogger("live-commands")

# ==================================================
# PERMISSIONS
# ==================================================

def has_permission(interaction: discord.Interaction) -> bool:
    if not interaction.guild:
        return False

    perms = interaction.user.guild_permissions
    return perms.administrator or perms.manage_guild


# ==================================================
# COMMAND REGISTRATION
# ==================================================

def register_live_commands(bot):

    group = app_commands.Group(
        name="live",
        description="Manage Twitch live notifications"
    )

    # ==================================================
    # ADD STREAMER
    # ==================================================

    @group.command(name="add")
    async def add(
        interaction: discord.Interaction,
        login: str,
        channel: discord.TextChannel,
        role: discord.Role = None
    ):
        if not has_permission(interaction):
            await interaction.response.send_message(
                "❌ Permission required (Manage Server / Administrator).",
                ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)

        try:
            twitch_api = bot.app_state.twitch_api

            # 🔍 Resolve Twitch user
            user = await twitch_api.resolve_user(login)

            if not user:
                await interaction.followup.send("❌ Twitch channel not found.")
                return

            guild_id = interaction.guild_id
            broadcaster_id = user["id"]

            # ==================================================
            # DB → STREAMER
            # ==================================================

            await add_streamer(
                bot.app_state.db,
                guild_id,
                broadcaster_id,
                channel.id
            )

            # ==================================================
            # GUILD CONFIG
            # ==================================================

            await upsert_guild_config(
                bot.app_state.db,
                guild_id,
                channel.id,
                role.id if role else None
            )

            # ==================================================
            # EVENTSUB SUBSCRIPTION
            # ==================================================

            try:
                await bot.app_state.eventsub_manager.subscribe_all(broadcaster_id)

            except Exception as e:
                logger.error("EventSub subscription failed: %s", e)
                await interaction.followup.send(
                    "⚠️ Streamer added, but EventSub subscription failed. Check logs."
                )
                return

            # ==================================================
            # SUCCESS RESPONSE
            # ==================================================

            await interaction.followup.send(
                f"✅ Now tracking **{user['display_name']}**\n"
                f"📺 Channel: {channel.mention}",
            )

        except Exception as e:
            logger.exception("Add command failed: %s", e)
            await interaction.followup.send(
                "❌ An unexpected error occurred."
            )

    # ==================================================
    # REMOVE STREAMER
    # ==================================================

    @group.command(name="remove")
    async def remove(
        interaction: discord.Interaction,
        login: str
    ):
        if not has_permission(interaction):
            await interaction.response.send_message(
                "❌ Permission required (Manage Server / Administrator).",
                ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)

        try:
            twitch_api = bot.app_state.twitch_api

            user = await twitch_api.resolve_user(login)

            if not user:
                await interaction.followup.send("❌ Twitch channel not found.")
                return

            await remove_streamer(
                bot.app_state.db,
                interaction.guild_id,
                user["id"]
            )

            await interaction.followup.send(
                f"🛑 Stopped tracking **{user['display_name']}**"
            )

        except Exception as e:
            logger.exception("Remove command failed: %s", e)
            await interaction.followup.send(
                "❌ An unexpected error occurred."
            )

    # ==================================================
    # REGISTER COMMAND GROUP
    # ==================================================

    bot.tree.add_command(group)
