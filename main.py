import os
import discord
from discord.ext import commands
from discord import app_commands

GUILD_ID = 1446560723122520207

# ==============================
# CONFIG
# ==============================

PROJECT_NAME = "kevkevy's gaming new bot"

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
# EMBED BUILDER
# ==============================

def build_embed(title, description, platform=None, thumbnail_url=None, page_info=None):
    color = PLATFORM_COLORS.get(platform, 0x5865F2)

    embed = discord.Embed(
        title=title,
        description=description,
        color=color
    )

    if thumbnail_url:
        embed.set_thumbnail(url=thumbnail_url)

    if page_info:
        embed.set_footer(text=f"{PROJECT_NAME} • {page_info}")
    else:
        embed.set_footer(text=f"{PROJECT_NAME}")

    return embed

# ==============================
# PAGINATION VIEW
# ==============================

class PaginationView(discord.ui.View):
    def __init__(self, interaction, pages):
        super().__init__(timeout=300)  # 5 dakika aktif
        self.interaction = interaction
        self.pages = pages
        self.current_page = 0

    async def update_message(self, interaction):
        await interaction.response.edit_message(
            embed=self.pages[self.current_page],
            view=self
        )

    @discord.ui.button(label="Previous", style=discord.ButtonStyle.secondary)
    async def previous_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_page > 0:
            self.current_page -= 1
        await self.update_message(interaction)

    @discord.ui.button(label="Next", style=discord.ButtonStyle.primary)
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_page < len(self.pages) - 1:
            self.current_page += 1
        await self.update_message(interaction)

    async def on_timeout(self):
        # Timeout olunca butonları disable edelim ama hata üretmesin
        for item in self.children:
            item.disabled = True
        try:
            await self.message.edit(view=self)
        except:
            pass

# ==============================
# MOCK DATA (TEST AMAÇLI)
# ==============================

def generate_mock_discounts():
    data = []
    for i in range(1, 7):
        data.append({
            "title": f"Game {i}",
            "discount": f"{70+i}% OFF",
            "platform": "steam",
            "thumbnail": "https://cdn.cloudflare.steamstatic.com/steam/apps/570/header.jpg"
        })
    return data

# ==============================
# COMMANDS
# ==============================

@bot.tree.command(name="game", description="Game related commands", guild=discord.Object(id=GUILD_ID))
async def game_group(interaction: discord.Interaction):
    await interaction.response.send_message("Use subcommands.", ephemeral=True)

# ------------------------------
# /game discounts
# ------------------------------

@bot.tree.command(name="game_discounts", description="View major game discounts", guild=discord.Object(id=GUILD_ID))
async def game_discounts(interaction: discord.Interaction):

    discounts = generate_mock_discounts()

    pages = []
    items_per_page = 2

    for i in range(0, len(discounts), items_per_page):
        chunk = discounts[i:i+items_per_page]

        description = ""
        for item in chunk:
            description += f"**{item['title']}**\n"
            description += f"Discount: {item['discount']}\n\n"

        embed = build_embed(
            title="🎮 Major Game Discounts",
            description=description,
            platform=chunk[0]["platform"],
            thumbnail_url=chunk[0]["thumbnail"],
            page_info=f"Page {len(pages)+1}"
        )

        pages.append(embed)

    view = PaginationView(interaction, pages)
    message = await interaction.response.send_message(embed=pages[0], view=view)
    view.message = await interaction.original_response()

# ------------------------------
# /twitch badges
# ------------------------------

@bot.tree.command(name="twitch_badges", description="View new Twitch badges", guild=discord.Object(id=GUILD_ID))
async def twitch_badges(interaction: discord.Interaction):

    badges = generate_mock_discounts()  # mock reuse

    pages = []
    items_per_page = 2

    for i in range(0, len(badges), items_per_page):
        chunk = badges[i:i+items_per_page]

        description = ""
        for item in chunk:
            description += f"**{item['title']} Badge**\n"
            description += f"Available Now\n\n"

        embed = build_embed(
            title="🟣 New Twitch Badges",
            description=description,
            platform="twitch",
            thumbnail_url=chunk[0]["thumbnail"],
            page_info=f"Page {len(pages)+1}"
        )

        pages.append(embed)

    view = PaginationView(interaction, pages)
    await interaction.response.send_message(embed=pages[0], view=view)
    view.message = await interaction.original_response()

# ==============================
# READY EVENT
# ==============================

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    try:
        synced = await bot.tree.sync(guild=discord.Object(id=GUILD_ID))
        print(f"Synced {len(synced)} commands to guild.")
    except Exception as e:
        print(e)

# ==============================
# RUN
# ==============================

if __name__ == "__main__":
    TOKEN = os.getenv("DISCORD_TOKEN")
    bot.run(TOKEN)
