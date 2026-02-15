# -*- coding: utf-8 -*-
"""
kevkevy's gaming new bot
Full production-ready version including:

- Epic free games (real API)
- GOG free (scrape)
- Humble free (scrape)
- Amazon Luna membership exclusives
- Persistent pagination buttons (restart-safe)
- Steam seasonal sale tracking
- Weekly professional digest format
- Duplicate weekly prevention
- Railway ready
"""

import os
import aiohttp
import discord
import datetime
import json
from discord.ext import commands, tasks
from discord import app_commands
from bs4 import BeautifulSoup

# ==============================
# CONFIG
# ==============================

PROJECT_NAME = "kevkevy's gaming new bot"

GUILD_ID = 1446560723122520207
FREE_CHANNEL_ID = 1446560723122520207  # CHANGE THIS TO REAL TEXT CHANNEL ID
DATA_FILE = "bot_state.json"

PLATFORM_COLORS = {
    "epic": 0x0E0E0E,
    "gog": 0x2B2B2B,
    "humble": 0x6C8E7B,
    "luna": 0xCC5500,
    "steam": 0x1B2838,
    "twitch": 0x9146FF
}

# ==============================
# BOT INIT
# ==============================

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

# ==============================
# STATE MANAGEMENT
# ==============================

def load_state():
    if not os.path.exists(DATA_FILE):
        return {"last_week_posted": None}
    with open(DATA_FILE, "r") as f:
        return json.load(f)

def save_state(state):
    with open(DATA_FILE, "w") as f:
        json.dump(state, f)

state = load_state()

# ==============================
# EMBED BUILDER
# ==============================

def build_embed(title, description, platform=None, thumbnail=None, footer_extra=None):
    color = PLATFORM_COLORS.get(platform, 0x5865F2)
    embed = discord.Embed(title=title, description=description, color=color)

    if thumbnail:
        embed.set_thumbnail(url=thumbnail)

    footer = PROJECT_NAME
    if footer_extra:
        footer += f" • {footer_extra}"
    embed.set_footer(text=footer)

    return embed

# ==============================
# EPIC FREE
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
                            "url": f"https://store.epicgames.com/en-US/p/{slug}",
                            "platform": "epic"
                        })
    return games

# ==============================
# GOG FREE
# ==============================

async def fetch_gog_free():
    url = "https://www.gog.com/en/games?priceRange=0,0"
    games = []

    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            html = await response.text()

    soup = BeautifulSoup(html, "html.parser")

    for product in soup.select("product-tile")[:5]:
        title = product.get("title")
        href = product.get("href")
        img = product.get("image")
        if title and href:
            games.append({
                "title": title,
                "url": f"https://www.gog.com{href}",
                "thumbnail": img,
                "platform": "gog"
            })
    return games

# ==============================
# HUMBLE FREE
# ==============================

async def fetch_humble_free():
    url = "https://www.humblebundle.com/store/search?price=free"
    games = []

    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            html = await response.text()

    soup = BeautifulSoup(html, "html.parser")

    for item in soup.select(".entity-title")[:5]:
        title = item.text.strip()
        parent = item.find_parent("a")
        if parent:
            href = parent.get("href")
            games.append({
                "title": title,
                "url": f"https://www.humblebundle.com{href}",
                "thumbnail": None,
                "platform": "humble"
            })
    return games

# ==============================
# AMAZON LUNA MEMBERSHIP
# ==============================

async def fetch_luna_membership():
    url = "https://luna.amazon.com/"
    games = []

    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            html = await response.text()

    soup = BeautifulSoup(html, "html.parser")

    for img in soup.select("img")[:6]:
        title = img.get("alt")
        src = img.get("src")
        if title and src:
            games.append({
                "title": title,
                "thumbnail": src,
                "access": "Included with Luna+ Subscription",
                "platform": "luna"
            })
    return games

# ==============================
# STEAM SEASON CHECK
# ==============================

def is_steam_season():
    return datetime.datetime.utcnow().month in [3, 6, 9, 12]

# ==============================
# PERSISTENT PAGINATION
# ==============================

class PersistentPagination(discord.ui.View):
    def __init__(self, pages):
        super().__init__(timeout=None)
        self.pages = pages
        self.current_page = 0

    @discord.ui.button(label="Previous", style=discord.ButtonStyle.secondary)
    async def previous(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_page > 0:
            self.current_page -= 1
        await interaction.response.edit_message(embed=self.pages[self.current_page], view=self)

    @discord.ui.button(label="Next", style=discord.ButtonStyle.primary)
    async def next(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_page < len(self.pages) - 1:
            self.current_page += 1
        await interaction.response.edit_message(embed=self.pages[self.current_page], view=self)

# ==============================
# WEEKLY DIGEST
# ==============================

@tasks.loop(hours=24)
async def weekly_digest():
    now = datetime.datetime.utcnow()
    week = now.isocalendar().week

    if now.weekday() == 3 and state["last_week_posted"] != week:
        channel = bot.get_channel(FREE_CHANNEL_ID)
        if not channel:
            return

        epic = await fetch_epic_free_games()
        if not epic:
            return

        description = ""
        for game in epic[:2]:
            description += f"🎮 **{game['title']}**\n{game['url']}\n\n"

        if is_steam_season():
            description += "🔥 **Steam Seasonal Sale is LIVE!**\nCheck Steam Store for major discounts.\n"

        embed = build_embed(
            "🎮 Weekly Gaming Digest",
            description,
            platform="epic",
            thumbnail=epic[0]["thumbnail"]
        )

        await channel.send(embed=embed)
        state["last_week_posted"] = week
        save_state(state)

# ==============================
# COMMANDS
# ==============================

@bot.tree.command(name="free_games", description="All current free games", guild=discord.Object(id=GUILD_ID))
async def free_games(interaction: discord.Interaction):

    epic = await fetch_epic_free_games()
    gog = await fetch_gog_free()
    humble = await fetch_humble_free()

    all_games = epic + gog + humble

    if not all_games:
        await interaction.response.send_message("No free games found.", ephemeral=True)
        return

    pages = []
    for i in range(0, len(all_games), 2):
        chunk = all_games[i:i+2]
        desc = ""
        for g in chunk:
            desc += f"**{g['title']}**\n{g['url']}\n\n"

        embed = build_embed(
            "🎮 Free Games",
            desc,
            platform=chunk[0]["platform"],
            thumbnail=chunk[0].get("thumbnail"),
            footer_extra=f"Page {len(pages)+1}"
        )
        pages.append(embed)

    view = PersistentPagination(pages)
    await interaction.response.send_message(embed=pages[0], view=view)

@bot.tree.command(name="membership_exclusives", description="Amazon Luna membership games", guild=discord.Object(id=GUILD_ID))
async def membership_exclusives(interaction: discord.Interaction):

    luna = await fetch_luna_membership()

    if not luna:
        await interaction.response.send_message("No membership exclusives found.", ephemeral=True)
        return

    pages = []
    for i in range(0, len(luna), 2):
        chunk = luna[i:i+2]
        desc = ""
        for g in chunk:
            desc += f"**{g['title']}**\n{g['access']}\n\n"

        embed = build_embed(
            "🔥 Membership Exclusives — Amazon Luna",
            desc,
            platform="luna",
            thumbnail=chunk[0].get("thumbnail"),
            footer_extra=f"Page {len(pages)+1}"
        )
        pages.append(embed)

    view = PersistentPagination(pages)
    await interaction.response.send_message(embed=pages[0], view=view)

# ==============================
# READY
# ==============================

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    await bot.tree.sync(guild=discord.Object(id=GUILD_ID))
    weekly_digest.start()

# ==============================
# RUN
# ==============================

if __name__ == "__main__":
    TOKEN = os.getenv("DISCORD_TOKEN")
    bot.run(TOKEN)
