# commands/reminder.py
# ⏰ Set async reminders

import asyncio
import discord
from discord import app_commands
from datetime import datetime, timezone, timedelta

def register_reminder(group):
    @group.command(name="reminder", description="⏰ Set a reminder (1–1440 minutes)")
    async def reminder(interaction: discord.Interaction, minutes: int, message: str):
        if not (1 <= minutes <= 1440):
            await interaction.response.send_message("❌ Minutes must be between 1 and 1440.", ephemeral=True)
            return

        fire_at = datetime.now(timezone.utc) + timedelta(minutes=minutes)
        fire_ts = int(fire_at.timestamp())

        embed = discord.Embed(
            title="⏰ Reminder set!",
            description=f"I'll remind you <t:{fire_ts}:R>.\n\n📝 **{message}**",
            color=0x2ECC71,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

        await asyncio.sleep(minutes * 60)

        fire_embed = discord.Embed(title="⏰ Reminder!", description=f"📝 **{message}**", color=0xF5A623)
        await interaction.followup.send(content=interaction.user.mention, embed=fire_embed)
