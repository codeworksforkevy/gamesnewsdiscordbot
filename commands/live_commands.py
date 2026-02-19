import json
import os
import discord
from discord import app_commands
from services.twitch_api import resolve_user

DATA_FILE = "data/streamers.json"

def load_streamers():
    if not os.path.exists(DATA_FILE):
        return {}
    with open(DATA_FILE, "r") as f:
        return json.load(f)

def save_streamers(data):
    os.makedirs("data", exist_ok=True)
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2)

def has_permission(interaction: discord.Interaction):
    perms = interaction.user.guild_permissions
    return perms.administrator or perms.manage_guild

def register_live_commands(bot):

    group = app_commands.Group(name="live", description="Manage live streamers")

    @group.command(name="add")
    async def add(interaction: discord.Interaction, login: str):

        if not has_permission(interaction):
            await interaction.response.send_message("Admin or mod only.", ephemeral=True)
            return

        user = await resolve_user(login)
        if not user:
            await interaction.response.send_message("Streamer not found.", ephemeral=True)
            return

        data = load_streamers()
        data[user["id"]] = user
        save_streamers(data)

        await interaction.response.send_message(
            f"Added {user['display_name']}",
            ephemeral=True
        )

    @group.command(name="remove")
    async def remove(interaction: discord.Interaction, login: str):

        if not has_permission(interaction):
            await interaction.response.send_message("Admin or mod only.", ephemeral=True)
            return

        data = load_streamers()
        for sid, info in list(data.items()):
            if info["login"].lower() == login.lower():
                del data[sid]
                save_streamers(data)
                await interaction.response.send_message("Removed.", ephemeral=True)
                return

        await interaction.response.send_message("Not found.", ephemeral=True)

    @group.command(name="list")
    async def list_cmd(interaction: discord.Interaction):

        data = load_streamers()
        if not data:
            await interaction.response.send_message("No streamers tracked.", ephemeral=True)
            return

        names = [v["display_name"] for v in data.values()]
        await interaction.response.send_message("\n".join(names), ephemeral=True)

    bot.tree.add_command(group)
