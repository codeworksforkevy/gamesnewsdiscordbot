from __future__ import annotations
import os
import asyncio
import logging
from aiohttp import web
import discord
from discord.ext import commands

# ==============================
# ENV
# ==============================

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID", "0"))
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL")

if not DISCORD_TOKEN:
    raise RuntimeError("DISCORD_TOKEN missing")

# ==============================
# LOGGING
# ==============================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
)

logger = logging.getLogger("find-a-curie")

# ==============================
# DISCORD
# ==============================

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

# ==============================
# IMPORTS
# ==============================

from commands.live_commands import register_live_commands
from services.eventsub_server import create_eventsub_app

# ==============================
# READY
# ==============================

@bot.event
async def on_ready():
    logger.info("Bot ready: %s", bot.user)
    await tree.sync()
    logger.info("Global sync complete.")

# ==============================
# WEB SERVER
# ==============================

async def health(request):
    return web.json_response({"status": "ok"})

async def start_web_server():
    app = create_eventsub_app(bot, CHANNEL_ID)
    app.router.add_get("/", health)

    runner = web.AppRunner(app)
    await runner.setup()

    port = int(os.getenv("PORT", "8080"))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

    logger.info("Web server running on port %s", port)

# ==============================
# MAIN
# ==============================

async def main():
    register_live_commands(bot)
    await start_web_server()
    await bot.start(DISCORD_TOKEN)

if __name__ == "__main__":
    asyncio.run(main())
