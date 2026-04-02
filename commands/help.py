# commands/help.py

import discord
from discord import app_commands
import logging

logger = logging.getLogger("help")

# Kanaal waar feature-suggestions naartoe worden gestuurd
# Dit kanaal is alleen zichtbaar voor mods en de bot
SUGGESTION_CHANNEL_ID = 1446562017342390383  # mod-only kanaal


def _build_embed(lang: str, is_staff: bool = False) -> discord.Embed:
    is_nl = lang == "nl"
    embed = discord.Embed(title="🖥️ Find a Curie — Command Guide", color=0x9146FF)

    if is_nl:
        embed.add_field(name="🟣 Live tracking", value=(
            "Volg Twitch-creators en ontvang realtime meldingen.\n"
            "`/live add` • `/live remove` • `/live list` • `/live set-channel`"
        ), inline=False)
        embed.add_field(name="<👨‍💻♨⚛> Gratis games", value=(
            "Actuele gratis games van Epic, Steam, GOG en Humble Bundle.\n"
            "`/freegames` • `/game_discounts`"
        ), inline=False)
        embed.add_field(name="👨‍💻 Amazon Luna", value=(
            "Gratis games via Amazon Prime Gaming / Luna+.\n`/membership_exclusives`"
        ), inline=False)
        embed.add_field(name="🏅 Twitch badges",
            value="Bekijk wereldwijde Twitch-badges.\n`/twitch_badges`", inline=False)
        embed.add_field(name="📟 Persoonlijke meldingen", value=(
            "Ontvang een DM wanneer een streamer live gaat.\n"
            "`/notify add` • `/notify remove` • `/notify list`"
        ), inline=False)
        embed.add_field(name="☕︎ Statistieken",
            value="Bekijk hoe actief gevolgde streamers zijn.\n`/live stats`", inline=False)
        embed.add_field(name="🎬 Clips & Schema", value=(
            "Beste Twitch clips en aankomende streams.\n"
            "`/clip <streamer>` • `/schedule` • `/schedule <streamer>`"
        ), inline=False)
        if is_staff:
            embed.add_field(name="🛑LIVE 🎞️🎥 Aankondigingen  *(alleen admin)*", value=(
                "Post een streamaankondiging in het aankondigingskanaal.\n"
                "Vul een tijdstip in (bv. `21:00`) — de bot zet dat automatisch om naar een "
                "Discord-timestamp zodat iedereen het in zijn eigen tijdzone ziet.\n"
                "Laat het tijdstip leeg als je al live bent.\n"
                "`/announce message:<tekst> game:<spel> go_live_at:<tijd>`"
            ), inline=False)
        embed.add_field(name="모 Hulpmiddelen", value=(
            "Handige tools voor dagelijks Discord-gebruik.\n"
            "`/util convert` • `/util poll` • `/util reminder` • `/util timestamp`"
        ), inline=False)
        if is_staff:
            embed.add_field(name="₊˚✩ ₊˚💻⊹♡  Functie voorstellen", value=(
                "Heb je een idee voor een nieuwe functie? Stuur het rechtstreeks naar Sim!\n"
                "Jouw voorstel is privé — alleen mods kunnen het zien.\n"
                "`/suggest <jouw idee>`"
            ), inline=False)
        embed.set_footer(text="💬 Hulp nodig? Vraag het aan Sim. • 🇧🇪 Nederlands")
    else:
        embed.add_field(name="🟣 Live tracking", value=(
            "Follow Twitch creators and get real-time live notifications.\n"
            "`/live add` • `/live remove` • `/live list` • `/live set-channel`"
        ), inline=False)
        embed.add_field(name="<👨‍💻♨⚛> Free games", value=(
            "Current free games from Epic Games, Steam, GOG and Humble Bundle.\n"
            "`/freegames` • `/game_discounts`"
        ), inline=False)
        embed.add_field(name="👨‍💻 Amazon Luna", value=(
            "Free games via Amazon Prime Gaming / Luna+.\n`/membership_exclusives`"
        ), inline=False)
        embed.add_field(name="🏅 Twitch badges",
            value="Explore global Twitch badges.\n`/twitch_badges`", inline=False)
        embed.add_field(name="📟 Personal notifications", value=(
            "Get a DM when a streamer goes live — no server ping.\n"
            "`/notify add` • `/notify remove` • `/notify list`"
        ), inline=False)
        embed.add_field(name="☕︎ Stats",
            value="See how active tracked streamers are.\n`/live stats`", inline=False)
        embed.add_field(name="🎬 Clips & Schedule", value=(
            "Top Twitch clips and upcoming stream schedules.\n"
            "`/clip <streamer>` • `/schedule` • `/schedule <streamer>`"
        ), inline=False)
        if is_staff:
            embed.add_field(name="🛑LIVE 🎞️🎥 Announcements  *(admin only)*", value=(
                "Post a stream announcement to the announcements channel.\n"
                "Enter a time (e.g. `21:00`) — the bot converts it to a Discord timestamp "
                "so everyone sees it in their own timezone. Leave blank if you're live now.\n"
                "`/announce message:<text> game:<game> go_live_at:<time>`"
            ), inline=False)
        embed.add_field(name="모 Utilities", value=(
            "Handy tools for everyday Discord use.\n"
            "`/util convert` • `/util poll` • `/util reminder` • `/util timestamp`"
        ), inline=False)
        if is_staff:
            embed.add_field(name="‧₊˚✩ ₊˚💻⊹♡ Feature suggestions", value=(
                "Got an idea for a new feature? Send it to Sim!\n"
                "Your suggestion is private — only mods can see it.\n"
                "`/suggest <your idea>`"
            ), inline=False)
        embed.set_footer(text="💬 Need help? Ask Sim. • 🇬🇧 English")

    return embed


class LanguageToggle(discord.ui.View):
    def __init__(self, lang: str = "en", is_staff: bool = False):
        super().__init__(timeout=300)
        self.lang     = lang
        self.is_staff = is_staff
        self._refresh()

    def _refresh(self):
        self.clear_items()
        label = "🇧🇪 Bekijk in het Nederlands" if self.lang == "en" else "🇬🇧 View in English"
        btn = discord.ui.Button(label=label, style=discord.ButtonStyle.secondary)
        btn.callback = self._toggle
        self.add_item(btn)

    async def _toggle(self, interaction: discord.Interaction):
        self.lang = "nl" if self.lang == "en" else "en"
        self._refresh()
        await interaction.response.edit_message(
            embed=_build_embed(self.lang, is_staff=self.is_staff), view=self
        )

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


async def register(bot, app_state, session):

    @bot.tree.command(name="help", description="👾 View the Find a Curie command guide")
    async def help_command(interaction: discord.Interaction):
        # Staff check: admin or anyone who can manage messages (mods)
        perms    = interaction.user.guild_permissions
        is_staff = perms.administrator or perms.manage_guild or perms.manage_messages
        await interaction.response.send_message(
            embed=_build_embed("en", is_staff=is_staff),
            view=LanguageToggle("en", is_staff=is_staff),
        )

    # ── /suggest ──────────────────────────────────────────────────────────
    # Belgisch Nederlands commentaar:
    # Deze command laat iedereen een functievoorstel insturen.
    # Het voorstel wordt als embed gepost in het vastgelegde kanaal.
    # Sim (de ontwikkelaar) leest de voorstellen en beslist wat er gebouwd wordt.
    # Alleen gebruikers met "Manage Server" rechten kunnen dit gebruiken.

    @bot.tree.command(
        name="suggest",
        description="👩🏻‍💻📓✍🏻💡 Send a feature suggestion to Sim",
    )
    @app_commands.describe(
        idea="Beschrijf je idee zo duidelijk mogelijk / Describe your idea clearly",
    )
    async def suggest_command(interaction: discord.Interaction, idea: str):
        await interaction.response.defer(ephemeral=True)

        # Voorstelkanaal ophalen — eerst uit cache, dan via API
        # Belangrijk: dit kanaal is alleen zichtbaar voor mods
        try:
            channel = (
                interaction.guild.get_channel(SUGGESTION_CHANNEL_ID)
                or await bot.fetch_channel(SUGGESTION_CHANNEL_ID)
            )
        except Exception:
            channel = None

        if not channel:
            await interaction.followup.send(
                "❌ Suggestion channel not found. Ask Sim to configure `SUGGESTION_CHANNEL_ID`.",
                ephemeral=True,
            )
            return

        # Embed opbouwen: wie, het idee, tijdstip
        # Dit bericht wordt gepost in het mod-kanaal
        embed = discord.Embed(
            title="👩🏻‍💻📓✍🏻💡 Nieuw functievoorstel / Feature Suggestion",
            description=idea,
            color=0x89CFF0,  # baby blue
        )
        embed.set_author(
            name=str(interaction.user),
            icon_url=interaction.user.display_avatar.url,
        )
        embed.set_footer(text=f"Server: {interaction.guild.name}")
        embed.timestamp = discord.utils.utcnow()

        await channel.send(embed=embed)

        # Bevestiging — tweetalig zodat zowel NL als EN gebruikers het begrijpen
        await interaction.followup.send(
            "✅ Je voorstel is doorgestuurd naar Sim!\n"
            "✅ Your suggestion has been sent to Sim!",
            ephemeral=True,
        )

        logger.info(f"/suggest by {interaction.user} in {interaction.guild.name}: {idea[:80]}")
