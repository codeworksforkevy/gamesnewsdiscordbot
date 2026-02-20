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
# DISCORD SETUP
# ==============================

intents = discord.Intents.default()

bot = commands.Bot(
    command_prefix="!",
    intents=intents
)

tree = bot.tree

# ==============================
# IMPORTS (after bot init)
# ==============================

from commands.live_commands import register_live_commands
from services.eventsub_server import create_eventsub_app

# ==============================
# READY EVENT
# ==============================

@bot.event
async def on_ready():
    logger.info("Bot ready: %s", bot.user)

    try:
        synced = await tree.sync()
        logger.info("Global sync complete (%s commands).", len(synced))
    except Exception as e:
        logger.exception("Slash sync failed: %s", e)

# ==============================
# WEB SERVER
# ==============================

async def health(request):
    return web.json_response({"status": "ok"})


async def start_web_server():
    """
    Starts aiohttp server for:
    - Twitch EventSub webhook
    - Health check endpoint
    """

    app = await create_eventsub_app(bot)

    app.router.add_get("/", health)

    runner = web.AppRunner(app)
    await runner.setup()

    port = int(os.getenv("PORT", "8080"))

    site = web.TCPSite(
        runner,
        host="0.0.0.0",
        port=port
    )

    await site.start()

    logger.info("Web server running on port %s", port)


# ==============================
# MAIN
# ==============================

async def main():

    # Register slash commands
    register_live_commands(bot)

    # Start webhook server BEFORE bot login
    await start_web_server()

    # Start Discord bot
    await bot.start(DISCORD_TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
