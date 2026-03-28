import discord
import json
from pathlib import Path

from utils.pagination import RedisPagination
from constants import PLATFORM_COLORS

CACHE_FILE = Path("data/twitch_badges_cache.json")


async def register(bot, app_state, session):

    @bot.tree.command(
        name="twitch_badges",
        description="Show official Twitch global badges",
    )
    async def twitch_badges(interaction: discord.Interaction):

        await interaction.response.defer(thinking=True)

        if not CACHE_FILE.exists():
            await interaction.followup.send(
                "Badge cache not ready yet. Please try again in a few minutes.",
                ephemeral=True,
            )
            return

        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                badges = json.load(f)
        except Exception as e:
            await interaction.followup.send(
                f"❌ Failed to read badge cache: {e}", ephemeral=True
            )
            return

        if not badges:
            await interaction.followup.send(
                "No Twitch global badges found.", ephemeral=True
            )
            return

        pages = []

        for i in range(0, len(badges), 4):
            chunk      = badges[i:i + 4]
            desc_block = ""

            for badge in chunk:
                desc_block += (
                    f"**{badge.get('title', 'Unknown')}**\n"
                    f"{badge.get('description', '')}\n\n"
                )

            embed = discord.Embed(
                title="🏅 Global Twitch Badges",
                description=desc_block.strip(),
                color=PLATFORM_COLORS.get("twitch", 0x9146FF),
            )

            thumb = chunk[0].get("thumbnail") if chunk else None
            if thumb:
                embed.set_thumbnail(url=thumb)

            total_pages = (len(badges) + 3) // 4
            embed.set_footer(text=f"Twitch • Page {i // 4 + 1}/{total_pages}")
            pages.append(embed)

        view = RedisPagination(pages, interaction.user.id)
        await interaction.followup.send(embed=pages[0], view=view)
