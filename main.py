import asyncio
import aiohttp
import discord
from discord.ext import commands
from config import DISCORD_TOKEN

from commands.free_games import register_free_games
from commands.membership import register_luna
from commands.discounts import register_discounts
from commands.twitch_badges import register_twitch_badges


class GameBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        super().__init__(command_prefix="!", intents=intents)
        self.session = None

    async def setup_hook(self):
        # Session oluştur
        self.session = aiohttp.ClientSession()

        # Komutları register et
        await register_free_games(self, self.session)
        await register_luna(self, self.session)
        await register_discounts(self, self.session)
        await register_twitch_badges(self, self.session)

        # 👇 DEBUG DOĞRU YER
        print("Registered commands:", self.tree.get_commands())

        # Global sync
        await self.tree.sync()
        print("Global slash commands synced.")

    async def close(self):
        if self.session:
            await self.session.close()
        await super().close()


bot = GameBot()


@bot.event
async def on_ready():
    print(f"Bot ready: {bot.user}")


if __name__ == "__main__":
    asyncio.run(bot.start(DISCORD_TOKEN))
