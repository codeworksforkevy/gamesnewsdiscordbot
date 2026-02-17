import asyncio
import aiohttp
import discord
from discord.ext import tasks

from config import DISCORD_TOKEN, CACHE_UPDATE_INTERVAL

from commands.free_games import register_free_games
from commands.twitch_badges import register_twitch_badges
from tasks.freegames_updater import update_free_games
from tasks.twitch_updater import update_twitch_badges


# ==============================
# CONFIG
# ==============================

# 🔥 Kendi server ID'n buraya
GUILD_ID = 123456789012345678  # BURAYI DEGISTIR


# ==============================
# DISCORD CLIENT SETUP
# ==============================

intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = discord.app_commands.CommandTree(client)


# ==============================
# CACHE LOOP (60 min default)
# ==============================

@tasks.loop(seconds=CACHE_UPDATE_INTERVAL)
async def cache_loop():
    print("Running scheduled cache update...")

    async with aiohttp.ClientSession() as session:
        await update_free_games(session)
        await update_twitch_badges(session)

    print("Scheduled cache update complete.")


# ==============================
# READY EVENT
# ==============================

@client.event
async def on_ready():
    print(f"Bot ready: {client.user}")

    # 🔥 İlk açılışta cache doldur
    async with aiohttp.ClientSession() as session:
        await update_free_games(session)
        await update_twitch_badges(session)

    print("Initial cache populated.")

    # 🔥 Guild-based slash sync (instant)
    guild = discord.Object(id=GUILD_ID)
    await tree.sync(guild=guild)
    print("Slash commands synced to guild.")

    # Loop zaten çalışmıyorsa başlat
    if not cache_loop.is_running():
        cache_loop.start()


# ==============================
# MAIN
# ==============================

async def main():

    # 🔥 Command register işlemleri
    await register_free_games(tree)
    await register_twitch_badges(tree)

    # Bot start
    await client.start(DISCORD_TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
