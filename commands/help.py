# commands/help.py
import discord
from discord import app_commands
import logging

logger = logging.getLogger("help")
SUGGESTION_CHANNEL_ID = 1446562017342390383

async def register(bot, app_state, session):
    @bot.tree.command(name="suggest", description="Bot için yeni bir özellik veya fikir önerin.")
    async def suggest_cmd(interaction: discord.Interaction, idea: str):
        await interaction.response.defer(ephemeral=True)

        channel = None
        try:
            channel = interaction.guild.get_channel(SUGGESTION_CHANNEL_ID) or await bot.fetch_channel(SUGGESTION_CHANNEL_ID)
        except (discord.NotFound, discord.Forbidden):
            pass

        if not channel:
            await interaction.followup.send(
                "❌ Suggestion channel not found. Please inform Sim so she can configure `SUGGESTION_CHANNEL_ID`.",
                ephemeral=True
            )
            return

        embed = discord.Embed(
            title="👩🏻‍💻📓✍🏻💡 Nieuw functievoorstel / Feature Suggestion",
            description=idea,
            color=0x89CFF0
        )
        embed.set_author(name=str(interaction.user), icon_url=interaction.user.display_avatar.url)
        embed.set_footer(text=f"Server: {interaction.guild.name}")
        embed.timestamp = discord.utils.utcnow()

        try:
            await channel.send(embed=embed)
            await interaction.followup.send(
                "✅ Je voorstel is doorgestuurd!\n✅ Your suggestion has been successfully submitted!",
                ephemeral=True
            )
        except Exception as e:
            logger.error(f"/suggest failed: {e}")
            await interaction.followup.send("❌ Gönderim sırasında bir hata oluştu.", ephemeral=True)

    logger.info("help/suggest commands registered")
