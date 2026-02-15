import os
import aiohttp
import discord
import datetime
from discord.ext import commands, tasks
from discord import app_commands

# ==============================
# CONFIG
# ==============================

PROJECT_NAME = "kevkevy's gaming new bot"

GUILD_ID = 1446560723122520207
FREE_CHANNEL_ID = 1446560723122520207  # BURAYA GERÇEK TEXT CHANNEL ID GİR

PLATFORM_COLORS = {
    "epic": 0x0E0E0E,
    "gog": 0x2B2B2B,
    "humble": 0x6C8E7B,
    "luna": 0xCC5500,
    "steam": 0x1B2838,
    "twitch": 0x9146FF
}

last_week_posted = None  # duplicate engelleme

# ==============================
# BOT INIT
# ==============================

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

# ==============================
# EMBED BUILDER
# ==============================

def build_embed(title, description, platform=None, thumbnail=None, footer_extra=None):
    color = PLATFORM_COLORS.get(platform, 0x5865F2)

    embed = discord.Embed(
        title=title,
        description=description,
        color=color
    )

    if thumbnail:
        embed.set_thumbnail(url=thumbnail)

    footer_text = PROJECT_NAME
    if footer_extra:
        footer_text += f" • {footer_extra}"

    embed.set_footer(text=footer_text)
    return embed

# ==============================
# EPIC FREE FETCH
# ==============================

async def fetch_epic_free_games():
    url = "https://store-site-backend-static.ak.epicgames.com/freeGamesPromotions"

    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            data = await response.json()

    games = []
    elements = data["data"]["Catalog"]["searchStore"]["elements"]

    for game in elements:
        promotions = game.get("promotions")
        if promotions and promotions.get("promotionalOffers"):
            offers = promotions["promotionalOffers"]
            if offers:
                offer = offers[0]["promotionalOffers"][0]
                if offer["discountSetting"]["discountPercentage"] == 0:
                    slug = game.get("productSlug")
                    if slug:
                        games.append({
                            "title": game["title"],
                            "thumbnail": game["keyImages"][0]["url"],
                            "url": f"https://store.epicgames.com/en-US/p/{slug}"
                        })

    return games

# ==============================
# PAGINATION VIEW
# ==============================

class PaginationView(discord.ui.View):
    def __init__(self, pages):
        super().__init__(timeout=300)
        self.pages = pages
        self.current_page = 0
        self.message = None

    async def update(self, interaction):
        await interaction.response.edit_message(
            embed=self.pages[self.current_page],
            view=self
        )

    @discord.ui.button(label="Previous", style=discord.ButtonStyle.secondary)
    async def previous(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_page > 0:
            self.current_page -= 1
        await self.update(interaction)

    @discord.ui.button(label="Next", style=discord.ButtonStyle.primary)
    async def next(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_page < len(self.pages) - 1:
            self.current_page += 1
        await self.update(interaction)

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except:
                pass

# ==============================
# WEEKLY FREE SCHEDULER
# ==============================

@tasks.loop(hours=24)
async def weekly_free_check():
    global last_week_posted

    now = datetime.datetime.utcnow()
    current_week = now.isocalendar().week

    if now.weekday() == 3 and last_week_posted != current_week:
        channel = bot.get_channel(FREE_CHANNEL_ID)
        if channel:
            games = await fetch_epic_free_games()
            if games:
                description = ""
                for game in games[:2]:
                    description += f"**{game['title']}**\n"
                    description += f"[Claim Here]({game['url']})\n\n"

                embed = build_embed(
                    "🎮 Weekly Free Games — Epic",
                    description,
                    platform="epic",
                    thumbnail=games[0]["thumbnail"]
                )

                await channel.send(embed=embed)
                last_week_posted = current_week

# ==============================
# COMMANDS
# ==============================

@bot.tree.command(name="free_games", description="View current free games", guild=discord.Object(id=GUILD_ID))
async def free_games(interaction: discord.Interaction):
    games = await fetch_epic_free_games()

    if not games:
        await interaction.response.send_message("No free games found.", ephemeral=True)
        return

    description = ""
    for game in games[:2]:
        description += f"**{game['title']}**\n"
        description += f"[Claim Here]({game['url']})\n\n"

    embed = build_embed(
        "🎮 Free Games — Epic",
        description,
        platform="epic",
        thumbnail=games[0]["thumbnail"]
    )

    await interaction.response.send_message(embed=embed)

# ------------------------------
# MOCK DISCOUNT DATA
# ------------------------------

def mock_discounts():
    data = []
    for i in range(1, 7):
        data.append({
            "title": f"Discounted Game {i}",
            "discount": f"{70+i}% OFF",
            "thumbnail": "https://cdn.cloudflare.steamstatic.com/steam/apps/570/header.jpg"
        })
    return data

@bot.tree.command(name="game_discounts", description="View major game discounts", guild=discord.Object(id=GUILD_ID))
async def game_discounts(interaction: discord.Interaction):
    data = mock_discounts()

    pages = []
    for i in range(0, len(data), 2):
        chunk = data[i:i+2]

        desc = ""
        for item in chunk:
            desc += f"**{item['title']}**\n"
            desc += f"{item['discount']}\n\n"

        embed = build_embed(
            "🎮 Major Game Discounts",
            desc,
            platform="steam",
            thumbnail=chunk[0]["thumbnail"],
            footer_extra=f"Page {len(pages)+1}"
        )
        pages.append(embed)

    view = PaginationView(pages)
    await interaction.response.send_message(embed=pages[0], view=view)
    view.message = await interaction.original_response()

# ------------------------------
# TWITCH BADGES (MOCK)
# ------------------------------

@bot.tree.command(name="twitch_badges", description="View new Twitch badges", guild=discord.Object(id=GUILD_ID))
async def twitch_badges(interaction: discord.Interaction):
    data = mock_discounts()

    pages = []
    for i in range(0, len(data), 2):
        chunk = data[i:i+2]

        desc = ""
        for item in chunk:
            desc += f"**{item['title']} Badge**\nAvailable Now\n\n"

        embed = build_embed(
            "🟣 New Twitch Badges",
            desc,
            platform="twitch",
            thumbnail=chunk[0]["thumbnail"],
            footer_extra=f"Page {len(pages)+1}"
        )
        pages.append(embed)

    view = PaginationView(pages)
    await interaction.response.send_message(embed=pages[0], view=view)
    view.message = await interaction.original_response()

# ==============================
# READY
# ==============================

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    await bot.tree.sync(guild=discord.Object(id=GUILD_ID))
    weekly_free_check.start()

# ==============================
# RUN
# ==============================

if __name__ == "__main__":
    TOKEN = os.getenv("DISCORD_TOKEN")
    bot.run(TOKEN)
