import discord
from datetime import datetime, timezone


class Notifier:

    def __init__(self, bot):
        self.bot = bot

    # ==================================================
    # MAIN ENTRY
    # ==================================================

    async def stream_updated(self, broadcaster_id, old, new, change_type=None):

        channel = self.bot.get_channel(YOUR_CHANNEL_ID)

        embed = self.build_embed(old, new, change_type)

        await channel.send(embed=embed)

    # ==================================================
    # EMBED UX
    # ==================================================

    def build_embed(self, old, new, change_type):

        embed = discord.Embed(
            title="🔴 Stream Update",
            color=discord.Color.blurple(),
            timestamp=datetime.now(timezone.utc)
        )

        embed.add_field(
            name="💽 Title",
            value=f"`{old.get('title')} → {new.get('title')}`",
            inline=False
        )

        embed.add_field(
            name="🕹️ Game",
            value=f"`{old.get('game')} → {new.get('game')}`",
            inline=False
        )

        embed.add_field(
            name="👩‍💻 Change Type",
            value=change_type or "unknown",
            inline=False
        )

        return embed
