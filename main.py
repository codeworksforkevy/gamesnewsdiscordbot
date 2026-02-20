from __future__ import annotations
import os
import asyncio
import logging
from aiohttp import web, ClientSession
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

# ==============================
# IMPORT COMMAND MODULES
# ==============================

from commands.live_commands import register_live_commands
from commands.discounts import register as register_discounts
from commands.free_games import register as register_free_games
from commands.membership import register as register_membership
from commands.twitch_badges import register as register_twitch_badges

from services.eventsub_server import create_eventsub_app

# ==============================
# READY EVENT
# ==============================

@bot.event
async def on_ready():
    logger.info("Bot ready: %s", bot.user)

    try:
        synced = await bot.tree.sync()
        logger.info("Global sync complete (%s commands).", len(synced))
    except Exception as e:
        logger.exception("Slash sync failed: %s", e)

# ==============================
# WEB SERVER (EventSub)
# ==============================

async def health(request):
    return web.json_response({"status": "ok"})


async def start_web_server():
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

    async with ClientSession() as session:

        # ---- Register Commands ----
        register_live_commands(bot)
        await register_discounts(bot, session)
        await register_free_games(bot, session)
        await register_membership(bot, session)
        await register_twitch_badges(bot, session)

        # ---- Start Webhook Server ----
        await start_web_server()

        # ---- Start Discord Bot ----
        await bot.start(DISCORD_TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
