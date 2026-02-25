import discord
from discord import app_commands
import datetime


def register_timestamp(group):

    @group.command(name="timestamp", description="Generate Discord timestamp")
    @app_commands.describe(
        year="Year (YYYY)",
        month="Month (1-12)",
        day="Day (1-31)",
        hour="Hour (0-23)",
        minute="Minute (0-59)"
    )
    async def timestamp(
        interaction: discord.Interaction,
        year: int,
        month: int,
        day: int,
        hour: int,
        minute: int
    ):

        dt = datetime.datetime(year, month, day, hour, minute)
        unix = int(dt.timestamp())

        embed = discord.Embed(
            title="Generated Timestamp",
            description=f"<t:{unix}:F>\n`<t:{unix}:F>`",
            color=0x5865F2
        )

        await interaction.response.send_message(embed=embed)
