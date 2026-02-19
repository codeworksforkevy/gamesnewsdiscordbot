
import json
import os
import discord
from discord import app_commands

DATA_FILE = "data/streamers.json"

def load_streamers():
    if not os.path.exists(DATA_FILE):
        return []
    with open(DATA_FILE, "r") as f:
        return json.load(f).get("streamers", [])

def save_streamers(data):
    with open(DATA_FILE, "w") as f:
        json.dump({"streamers": data}, f, indent=2)

def register_live_commands(bot):

    group = app_commands.Group(name="live", description="Manage live streamers")

    @group.command(name="add")
    async def add(interaction: discord.Interaction, login: str):
        streamers = load_streamers()
        if login in streamers:
            await interaction.response.send_message("Already added.", ephemeral=True)
            return
        streamers.append(login)
        save_streamers(streamers)
        await interaction.response.send_message(f"Added {login}", ephemeral=True)

    @group.command(name="remove")
    async def remove(interaction: discord.Interaction, login: str):
        streamers = load_streamers()
        if login not in streamers:
            await interaction.response.send_message("Not found.", ephemeral=True)
            return
        streamers.remove(login)
        save_streamers(streamers)
        await interaction.response.send_message(f"Removed {login}", ephemeral=True)

    @group.command(name="list")
    async def list_cmd(interaction: discord.Interaction):
        streamers = load_streamers()
        if not streamers:
            await interaction.response.send_message("No streamers tracked.", ephemeral=True)
            return
        await interaction.response.send_message("\n".join(streamers), ephemeral=True)

    bot.tree.add_command(group)
