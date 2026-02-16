import discord
import aiohttp
from io import BytesIO
from discord import app_commands
from services.twitch import fetch_twitch_badges
from utils.pagination import RedisPagination
from config import PLATFORM_COLORS


TWITCH_FALLBACK_ICON = "https://static-cdn.jtvnw.net/emoticons/v2/25/default/dark/3.0"


async def download_image(session, url):
    try:
        async with session.get(url) as resp:
            if resp.status == 200:
                data = await resp.read()
                return BytesIO(data)
    except Exception:
        return None
    return None


async def register_twitch_badges(bot, session):

    async def badges_callback(interaction: discord.Interaction):

        await interaction.response.defer()

        try:
            badges = await fetch_twitch_badges(session)
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
        files = []

        for i in range(0, len(badges), 2):
            chunk = badges[i:i+2]
            description_block = ""

            for b in chunk:
                title = b.get("title", "Unknown Badge")
                description = b.get("description", "No description available.")
                description_block += f"**{title}**\n{description}\n\n"

            embed = discord.Embed(
                title="Global Badges",
                description=description_block.strip(),
                color=PLATFORM_COLORS.get("twitch", 0x9146FF)
            )

            primary_badge = chunk[0]
            thumbnail_url = primary_badge.get("thumbnail")

            file = None

            # 🔥 Görseli indir ve attachment yap
            if thumbnail_url and thumbnail_url.startswith("http"):
                image_bytes = await download_image(session, thumbnail_url)
                if image_bytes:
                    filename = f"badge_{i}.png"
                    file = discord.File(fp=image_bytes, filename=filename)
                    embed.set_thumbnail(url=f"attachment://{filename}")

            # Eğer indirilemezse fallback icon
            if not file:
                embed.set_thumbnail(url=TWITCH_FALLBACK_ICON)

            embed.set_footer(
                text=f"Twitch • Page {i//2+1}/{(len(badges)+1)//2}"
            )

            pages.append(embed)
            files.append(file)

        view = RedisPagination(pages, interaction.user.id)

        # İlk sayfayı dosya ile gönder
        await interaction.followup.send(
            embed=pages[0],
            file=files[0] if files[0] else None,
            view=view
        )

    command = app_commands.Command(
        name="twitch_badges",
        description="Show latest Twitch global badges",
        callback=badges_callback
    )

    bot.tree.add_command(command)


