# commands/help.py

import discord
from discord import app_commands


# ──────────────────────────────────────────────────────────────
# EMBED BUILDERS
# ──────────────────────────────────────────────────────────────

def _build_embed(lang: str) -> discord.Embed:

    is_nl = lang == "nl"

    embed = discord.Embed(
        title="🖥️ Find a Curie — Command Guide",
        color=0x9146FF,
    )

    if is_nl:
        embed.add_field(
            name="🟣 Live tracking",
            value=(
                "Volg Twitch-creators en ontvang realtime meldingen.\n"
                "`/live add` • `/live remove` • `/live list` • `/live set-channel`"
            ),
            inline=False,
        )
        embed.add_field(
            name="🎮 Gratis games",
            value=(
                "Actuele gratis games van Epic, Steam, GOG en Humble Bundle.\n"
                "`/freegames` • `/game_discounts`"
            ),
            inline=False,
        )
        embed.add_field(
            name="🌙 Amazon Luna",
            value=(
                "Gratis games via Amazon Prime Gaming / Luna+.\n"
                "`/membership_exclusives`"
            ),
            inline=False,
        )
        embed.add_field(
            name="🏅 Twitch badges",
            value="Bekijk wereldwijde Twitch-badges.\n`/twitch_badges`",
            inline=False,
        )
        embed.add_field(
            name="🔔 Persoonlijke meldingen",
            value=(
                "Ontvang een DM wanneer een streamer live gaat.\n"
                "`/notify add` • `/notify remove` • `/notify list`"
            ),
            inline=False,
        )
        embed.add_field(
            name="📊 Statistieken",
            value="Bekijk hoe actief gevolgde streamers zijn.\n`/live stats`",
            inline=False,
        )
        embed.add_field(
            name="🛠️ Hulpmiddelen",
            value=(
                "Handige tools voor dagelijks Discord-gebruik.\n"
                "`/util convert` • `/util poll` • `/util reminder` • `/util timestamp`"
            ),
            inline=False,
        )
        embed.set_footer(text="💬 Hulp nodig? Vraag het aan Sim. • 🇳🇱 Nederlands")
    else:
        embed.add_field(
            name="🟣 Live tracking",
            value=(
                "Follow Twitch creators and get real-time live notifications.\n"
                "`/live add` • `/live remove` • `/live list` • `/live set-channel`"
            ),
            inline=False,
        )
        embed.add_field(
            name="🎮 Free games",
            value=(
                "Current free games from Epic Games, Steam, GOG and Humble Bundle.\n"
                "`/freegames` • `/game_discounts`"
            ),
            inline=False,
        )
        embed.add_field(
            name="🌙 Amazon Luna",
            value=(
                "Free games via Amazon Prime Gaming / Luna+.\n"
                "`/membership_exclusives`"
            ),
            inline=False,
        )
        embed.add_field(
            name="🏅 Twitch badges",
            value="Explore global Twitch badges.\n`/twitch_badges`",
            inline=False,
        )
        embed.add_field(
            name="🔔 Personal notifications",
            value=(
                "Get a DM when a streamer goes live — no server ping.\n"
                "`/notify add` • `/notify remove` • `/notify list`"
            ),
            inline=False,
        )
        embed.add_field(
            name="📊 Stats",
            value="See how active tracked streamers are.\n`/live stats`",
            inline=False,
        )
        embed.add_field(
            name="🛠️ Utilities",
            value=(
                "Handy tools for everyday Discord use.\n"
                "`/util convert` • `/util poll` • `/util reminder` • `/util timestamp`"
            ),
            inline=False,
        )
        embed.set_footer(text="💬 Need help? Ask Sim. • 🇬🇧 English")

    return embed


# ──────────────────────────────────────────────────────────────
# LANGUAGE TOGGLE VIEW
# ──────────────────────────────────────────────────────────────

class LanguageToggle(discord.ui.View):
    """Button that swaps the embed between English and Dutch."""

    def __init__(self, lang: str = "en"):
        super().__init__(timeout=300)
        self.lang = lang
        self._refresh()

    def _refresh(self):
        self.clear_items()
        label = "🇳🇱 Bekijk in het Nederlands" if self.lang == "en" else "🇬🇧 View in English"
        btn = discord.ui.Button(label=label, style=discord.ButtonStyle.secondary)
        btn.callback = self._toggle
        self.add_item(btn)

    async def _toggle(self, interaction: discord.Interaction):
        self.lang = "nl" if self.lang == "en" else "en"
        self._refresh()
        await interaction.response.edit_message(embed=_build_embed(self.lang), view=self)

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


# ──────────────────────────────────────────────────────────────
# REGISTER
# ──────────────────────────────────────────────────────────────

async def register(bot, app_state, session):

    @bot.tree.command(name="help", description="👾 View the Find a Curie command guide")
    async def help_command(interaction: discord.Interaction):
        await interaction.response.send_message(
            embed=_build_embed("en"),
            view=LanguageToggle("en"),
        )
