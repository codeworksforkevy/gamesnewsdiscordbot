import discord
from discord import app_commands

from services.streamer_registry import add_streamer, remove_streamer
from services.guild_config import upsert_guild_config

# ==================================================
# PERMISSIONS
# ==================================================

def has_permission(interaction: discord.Interaction):
    if not interaction.guild:
        return False
    perms = interaction.user.guild_permissions
    return perms.administrator or perms.manage_guild


# ==================================================
# REGISTER COMMANDS
# ==================================================

def register_live_commands(bot):

    group = app_commands.Group(
        name="live",
        description="Manage Twitch live notifications"
    )

    # --------------------------------------------------
    # ADD
    # --------------------------------------------------

    @group.command(name="add")
    async def add(
        interaction: discord.Interaction,
        login: str,
        channel: discord.TextChannel,
        role: discord.Role = None
    ):
        if not has_permission(interaction):
            await interaction.response.send_message(
                "Permission required.", ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)

        twitch_api = bot.app_state.twitch_api
        user = await twitch_api.resolve_user(login)

        if not user:
            await interaction.followup.send("Channel not found.")
            return

        # DB kayıt
        await add_streamer(
            bot.app_state.db,
            interaction.guild_id,
            user["id"],
            channel.id
        )

        # guild config
        await upsert_guild_config(
            bot.app_state.db,
            interaction.guild_id,
            channel.id,
            role.id if role else None
        )

        # EventSub subscribe
        await bot.app_state.eventsub_manager.subscribe_all(user["id"])

        await interaction.followup.send(
            f"✅ Now tracking **{user['display_name']}** in {channel.mention}"
        )

    # --------------------------------------------------
    # REMOVE
    # --------------------------------------------------

    @group.command(name="remove")
    async def remove(interaction: discord.Interaction, login: str):

        if not has_permission(interaction):
            await interaction.response.send_message(
                "Permission required.", ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)

        twitch_api = bot.app_state.twitch_api
        user = await twitch_api.resolve_user(login)

        if not user:
            await interaction.followup.send("Channel not found.")
            return

        await remove_streamer(
            bot.app_state.db,
            interaction.guild_id,
            user["id"]
        )

        await interaction.followup.send(
            f"🛑 Stopped tracking **{user['display_name']}**"
        )

    bot.tree.add_command(group)
