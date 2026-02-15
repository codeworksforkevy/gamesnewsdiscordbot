import asyncio
import aiohttp
import discord
from discord.ext import commands
from config import DISCORD_TOKEN

from commands.free_games import register_free_games
from commands.membership import register_luna
from commands.discounts import register_discounts
from commands.twitch_badges import register_twitch_badges


intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

session = None
commands_loaded = False


@bot.event
async def on_ready():
    global commands_loaded

    print(f"Bot ready: {bot.user}")

    if not commands_loaded:
        # Register all commands AFTER bot is ready
        await register_free_games(bot, session)
        await register_luna(bot, session)
        await register_discounts(bot, session)
        await register_twitch_badges(bot, session)

        # Global sync (no guild ID)
        await bot.tree.sync()
        print("Global slash commands synced.")

        commands_loaded = True


async def main():
    global session
    session = aiohttp.ClientSession()

    try:
        await bot.start(DISCORD_TOKEN)
    finally:
        if session:
            await session.close()


if __name__ == "__main__":
    asyncio.run(main())

