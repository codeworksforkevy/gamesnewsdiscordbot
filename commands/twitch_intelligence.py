
import discord
from discord import app_commands

async def register(bot):

    group = app_commands.Group(
        name="twitch",
        description="Twitch Intelligence Platform"
    )

    @group.command(name="health")
    async def health(interaction: discord.Interaction):
        await interaction.response.send_message("Twitch Intelligence Platform running.")

    bot.tree.add_command(group)
