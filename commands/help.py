import discord
from discord import app_commands


async def register(bot, app_state, session):

    @bot.tree.command(
        name="help",
        description="View the Find a Curie command guide"
    )
    async def help_command(interaction: discord.Interaction):

        embed = discord.Embed(
            title="📚 Find a Curie — Command Guide",
            color=0x9146FF
        )

        # -------------------------------------------------
        # LIVE TRACKING
        # -------------------------------------------------
        embed.add_field(
            name="🟣 Live Tracking",
            value=(
                "**English**\n"
                "Follow Twitch creators and receive real-time live notifications.\n\n"
                "**Nederlands**\n"
                "Volg Twitch-creators en ontvang realtime live meldingen.\n\n"
                "**Commands**\n"
                "`/live add` • `/live remove` • `/live list`"
            ),
            inline=False
        )

        # -------------------------------------------------
        # FREE GAMES
        # -------------------------------------------------
        embed.add_field(
            name="🎮 Free Games",
            value=(
                "**English**\n"
                "View current free games and limited-time offers from Epic Games, Steam, GOG and Humble Bundle.\n\n"
                "**Nederlands**\n"
                "Bekijk actuele gratis games en tijdelijke aanbiedingen van Epic Games, Steam, GOG en Humble Bundle.\n\n"
                "**Commands**\n"
                "`/freegames` • `/game_discounts`"
            ),
            inline=False
        )

        # -------------------------------------------------
        # AMAZON LUNA
        # -------------------------------------------------
        embed.add_field(
            name="🌙 Amazon Luna Membership",
            value=(
                "**English**\n"
                "Receive updates on games offered through Amazon Luna's Prime membership program.\n\n"
                "**Nederlands**\n"
                "Ontvang updates over games die worden aangeboden via het Prime-lidmaatschapsprogramma van Amazon Luna.\n\n"
                "**Command**\n"
                "`/membership_exclusives`"
            ),
            inline=False
        )

        # -------------------------------------------------
        # TWITCH BADGES
        # -------------------------------------------------
        embed.add_field(
            name="🏅 Twitch Badges",
            value=(
                "**English**\n"
                "Explore global Twitch badges.\n\n"
                "**Nederlands**\n"
                "Bekijk wereldwijde Twitch-badges.\n\n"
                "**Command**\n"
                "`/twitch_badges`"
            ),
            inline=False
        )

        # -------------------------------------------------
        # UTILITIES
        # -------------------------------------------------
        embed.add_field(
            name="🛠 Utilities",
            value=(
                "**English**\n"
                "Helpful tools for everyday Discord use in the community.\n\n"
                "**Nederlands**\n"
                "Handige tools voor dagelijks Discord-gebruik binnen de community.\n\n"
                "**Commands**\n"
                "`/convert` • `/poll` • `/reminder` • `/timestamp` • `/register`"
            ),
            inline=False
        )

        embed.set_footer(text="Need help? Ask Sim for guidance.")

        await interaction.response.send_message(embed=embed)
