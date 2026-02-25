import discord
from discord import app_commands
import asyncio


def register_reminder(group):

    @group.command(name="reminder", description="Set a reminder in minutes")
    @app_commands.describe(
        minutes="Minutes until reminder",
        message="Reminder message"
    )
    async def reminder(
        interaction: discord.Interaction,
        minutes: int,
        message: str
    ):

        await interaction.response.send_message(
            f"Reminder set for {minutes} minutes."
        )

        await asyncio.sleep(minutes * 60)

        await interaction.followup.send(
            f"⏰ Reminder: {message}"
        )
