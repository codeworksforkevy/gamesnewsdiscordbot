import discord
from discord import app_commands
from services.twitch import (
    fetch_twitch_badges,
    fetch_official_global_badges
)
from utils.pagination import RedisPagination
from config import PLATFORM_COLORS


TWITCH_FALLBACK_ICON = "https://static-cdn.jtvnw.net/emoticons/v2/25/default/dark/3.0"


async def register_twitch_badges(bot, session):

    async def badges_callback(interaction: discord.Interaction):

        await interaction.response.defer()

        try:
            # 1️⃣ Streamdatabase metin verisi
            badges = await fetch_twitch_badges(session)

            # 2️⃣ Resmi Twitch thumbnail verisi
            official_badges = await fetch_official_global_badges(session)

        except Exception as e:
            await interaction.followup.send(
                f"Error fetching Twitch badges: {str(e)}",
                ephemeral=True
            )
            return

        if not badges:
            await interaction.followup.send(
                "No new Twitch badges found.",
                ephemeral=True
            )
            return

        pages = []

        for i in range(0, len(badges), 2):
            chunk = badges[i:i+2]
            desc = ""

            for b in chunk:
                title = b.get("title", "Unknown Badge")
                description = b.get("description", "No description available.")
                desc += f"**{title}**\n{description}\n\n"

            embed = discord.Embed(
                title="Global Badges",
                description=desc.strip(),
                color=PLATFORM_COLORS.get("twitch", 0x9146FF)
            )

            # -------------------------------
            # 🎯 THUMBNAIL HYBRID SYSTEM
            # -------------------------------

            primary_badge = chunk[0]
            badge_name = primary_badge.get("title", "").lower()

            thumbnail_url = None

            # 1️⃣ Öncelik: Official Twitch API
            if badge_name in official_badges:
                thumbnail_url = official_badges[badge_name]

            # 2️⃣ Fallback: streamdatabase thumbnail
            if not thumbnail_url:
                fallback_thumb = primary_badge.get("thumbnail")
                if (
                    fallback_thumb
                    and fallback_thumb.startswith("http")
                    and any(
                        fallback_thumb.lower().endswith(ext)
                        for ext in [".png", ".jpg", ".jpeg", ".webp"]
                    )
                ):
                    thumbnail_url = fallback_thumb

            # 3️⃣ Final fallback: Twitch icon
            if not thumbnail_url:
                thumbnail_url = TWITCH_FALLBACK_ICON

            embed.set_thumbnail(url=thumbnail_url)

            embed.set_footer(
                text=f"Twitch • Page {i//2+1}/{(len(badges)+1)//2}"
            )

            pages.append(embed)

        view = RedisPagination(pages, interaction.user.id)

        await interaction.followup.send(
            embed=pages[0],
            view=view
        )

    command = app_commands.Command(
        name="twitch_badges",
        description="Show latest Twitch global badges",
        callback=badges_callback
    )

    bot.tree.add_command(command)
