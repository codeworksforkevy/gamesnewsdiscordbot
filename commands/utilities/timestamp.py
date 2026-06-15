# commands/timestamp.py
# 🕐 Discord timestamp generator

import datetime
import discord
from discord import app_commands

FORMAT_OPTIONS = [
    ("t", "Short time", "16:20"),
    ("d", "Short date", "20/04/2021"),
    ("F", "Full date & time", "Tuesday, 20 April 2021 16:20"),
    ("R", "Relative", "2 months ago"),
]

def register_timestamp(group):
    @group.command(name="timestamp", description="🕐 Generate Discord timestamps")
    async def timestamp(interaction: discord.Interaction, year: int, month: int, day: int, hour: int = 0, minute: int = 0):
        try:
            dt = datetime.datetime(year, month, day, hour, minute, tzinfo=datetime.timezone.utc)
            unix = int(dt.timestamp())
        except ValueError as e:
            await interaction.response.send_message(f"❌ Invalid date: {e}", ephemeral=True)
            return

        lines = "\n".join(f"`<t:{unix}:{code}>` → <t:{unix}:{code}> *({label})*" for code, label, _ in FORMAT_OPTIONS)
        
        embed = discord.Embed(
            title="🕐 Discord Timestamps",
            description=f"**Date:** <t:{unix}:F>\n**Unix:** `{unix}`\n\n{lines}",
            color=0x5865F2
        )
        await interaction.response.send_message(embed=embed)
