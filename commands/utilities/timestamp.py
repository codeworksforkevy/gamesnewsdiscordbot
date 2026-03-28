import datetime
import discord
from discord import app_commands


FORMAT_OPTIONS: list[tuple[str, str, str]] = [
    # (Discord format code, label, example shape)
    ("t", "Short time",      "16:20"),
    ("T", "Long time",       "16:20:30"),
    ("d", "Short date",      "20/04/2021"),
    ("D", "Long date",       "20 April 2021"),
    ("f", "Date & time",     "20 April 2021 16:20"),
    ("F", "Full date & time","Tuesday, 20 April 2021 16:20"),
    ("R", "Relative",        "2 months ago / in 3 hours"),
]


def register_timestamp(group):

    @group.command(name="timestamp", description="🕐 Generate Discord timestamps for any date")
    @app_commands.describe(
        year="Year (e.g. 2025)",
        month="Month (1–12)",
        day="Day (1–31)",
        hour="Hour in 24h format (0–23, default 0)",
        minute="Minute (0–59, default 0)",
    )
    async def timestamp(
        interaction: discord.Interaction,
        year: int,
        month: int,
        day: int,
        hour: int = 0,
        minute: int = 0,
    ):
        try:
            dt   = datetime.datetime(year, month, day, hour, minute,
                                     tzinfo=datetime.timezone.utc)
            unix = int(dt.timestamp())
        except ValueError as e:
            return await interaction.response.send_message(
                f"❌ Invalid date: {e}",
                ephemeral=True,
            )

        lines = "\n".join(
            f"`<t:{unix}:{code}>` → <t:{unix}:{code}>  *({label})*"
            for code, label, _ in FORMAT_OPTIONS
        )

        embed = discord.Embed(
            title="🕐 Discord Timestamps",
            description=(
                f"**Date:** <t:{unix}:F>\n"
                f"**Unix:** `{unix}`\n\n"
                f"{lines}"
            ),
            color=0x5865F2,
        )
        embed.set_footer(
            text="🖥️ Copy any format tag and paste it anywhere in Discord"
        )

        await interaction.response.send_message(embed=embed)
