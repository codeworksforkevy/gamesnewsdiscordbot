import asyncio
import discord
from discord import app_commands


def register_reminder(group):

    @group.command(name="reminder", description="⏰ Set a reminder (up to 1440 minutes)")
    @app_commands.describe(
        minutes="Minutes from now (1–1440)",
        message="What to remind you about",
    )
    async def reminder(
        interaction: discord.Interaction,
        minutes: int,
        message: str,
    ):
        if minutes < 1 or minutes > 1440:
            return await interaction.response.send_message(
                "❌ Minutes must be between **1** and **1440** (24 hours).",
                ephemeral=True,
            )

        from datetime import datetime, timezone, timedelta
        fire_at    = datetime.now(timezone.utc) + timedelta(minutes=minutes)
        fire_ts    = int(fire_at.timestamp())

        embed = discord.Embed(
            title="⏰ Reminder set!",
            description=(
                f"I'll remind you <t:{fire_ts}:R> at <t:{fire_ts}:t>.\n\n"
                f"📝 **{message}**"
            ),
            color=0x2ECC71,
        )
        embed.set_footer(text=f"🖥️ Reminder for {interaction.user.display_name}")

        await interaction.response.send_message(embed=embed, ephemeral=True)

        await asyncio.sleep(minutes * 60)

        try:
            fire_embed = discord.Embed(
                title="⏰ Reminder!",
                description=f"📝 **{message}**",
                color=0xF5A623,
            )
            fire_embed.set_footer(text="🖥️ Your reminder from Find a Curie")
            await interaction.followup.send(
                content=interaction.user.mention,
                embed=fire_embed,
                ephemeral=False,
            )
        except Exception:
            pass
