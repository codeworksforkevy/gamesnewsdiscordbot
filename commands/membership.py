import discord
from discord import app_commands

from services.luna import fetch_luna_membership
from utils.pagination import RedisPagination
from config import PLATFORM_COLORS


async def register(bot, app_state, session):

    async def membership_callback(interaction: discord.Interaction):

        await interaction.response.defer(thinking=True)

        try:
            luna = await fetch_luna_membership(session)
        except Exception as e:
            await interaction.followup.send(
                f"❌ Error fetching membership games: {e}", ephemeral=True
            )
            return

        if not luna:
            await interaction.followup.send(
                "No Prime Gaming / Luna+ games found right now.\n"
                "This can happen if Amazon's page structure has changed.",
                ephemeral=True,
            )
            return

        pages = []

        for i in range(0, len(luna), 2):
            chunk = luna[i:i + 2]
            desc  = ""

            for g in chunk:
                title    = g.get("title", "Unknown")
                end_time = g.get("end_time", "")
                end_str  = ""

                if end_time:
                    try:
                        from datetime import datetime
                        dt     = datetime.fromisoformat(end_time.replace("Z", "+00:00"))
                        ts     = int(dt.timestamp())
                        end_str = f"\n⏰ Ends <t:{ts}:R>"
                    except Exception:
                        pass

                desc += f"**{title}**\nFree with Prime Gaming{end_str}\n\n"

            embed = discord.Embed(
                title="🌙 Amazon Prime Gaming — Free Games",
                description=desc.strip(),
                color=PLATFORM_COLORS.get("luna", 0x00A8E1),
                url="https://gaming.amazon.com/home",
            )

            thumb = chunk[0].get("thumbnail") if chunk else None
            if thumb:
                embed.set_thumbnail(url=thumb)

            embed.set_footer(text=f"Prime Gaming • Page {i // 2 + 1}")
            pages.append(embed)

        view = RedisPagination(pages, interaction.user.id)
        await interaction.followup.send(embed=pages[0], view=view)

    bot.tree.add_command(
        app_commands.Command(
            name="membership_exclusives",
            description="Show Amazon Prime Gaming / Luna+ free games",
            callback=membership_callback,
        )
    )
