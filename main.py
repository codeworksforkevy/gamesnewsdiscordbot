
import asyncio, aiohttp, discord
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
    print("Cache updated")

@client.event
async def on_ready():
    print(f"Bot ready: {client.user}")
    await tree.sync()
    cache_loop.start()

async def main():
    await register_free_games(tree)
    await register_twitch_badges(tree)
    await client.start(DISCORD_TOKEN)

if __name__ == "__main__":
    asyncio.run(main())
