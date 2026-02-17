import asyncio
import aiohttp
import discord
from discord.ext import tasks
from config import DISCORD_TOKEN, CACHE_UPDATE_INTERVAL

from commands.free_games import register_free_games
from commands.twitch_badges import register_twitch_badges
from tasks.freegames_updater import update_free_games
from tasks.twitch_updater import update_twitch_badges

intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = discord.app_commands.CommandTree(client)


@tasks.loop(seconds=CACHE_UPDATE_INTERVAL)
async def cache_loop():
    async with aiohttp.ClientSession() as session:
        await update_free_games(session)
        await update_twitch_badges(session)
    print("Scheduled cache update complete.")


@client.event
async def on_ready():
    print(f"Bot ready: {client.user}")

    # 🔥 İlk başlangıçta cache doldur
    async with aiohttp.ClientSession() as session:
        await update_free_games(session)
        await update_twitch_badges(session)

    print("Initial cache populated.")

    await tree.sync()
    print("Slash commands synced.")

    if not cache_loop.is_running():
        cache_loop.start()


async def main():
    await register_free_games(tree)
    await register_twitch_badges(tree)
    await client.start(DISCORD_TOKEN)


if __name__ == "__main__":
    asyncio.run(main())

