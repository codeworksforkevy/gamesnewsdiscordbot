import asyncio
import aiohttp
import discord
from discord.ext import commands
from config import DISCORD_TOKEN, GUILD_ID

from commands.free_games import register_free_games
from commands.membership import register_luna
from commands.discounts import register_discounts
from commands.twitch_badges import register_twitch_badges

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

session = None


@bot.event
async def on_ready():
    print(f"Bot ready: {bot.user}")
    await bot.tree.sync(guild=discord.Object(id=GUILD_ID))
    print("Slash commands synced.")


async def setup_commands():
    await register_free_games(bot, session)
    await register_luna(bot, session)
    await register_discounts(bot, session)
    await register_twitch_badges(bot, session)


async def main():
    global session
    session = aiohttp.ClientSession()

    try:
        await setup_commands()
        await bot.start(DISCORD_TOKEN)
    finally:
        if session:
            await session.close()


if __name__ == "__main__":
    asyncio.run(main())
