import asyncio
import logging
import discord
from services.luna import fetch_luna_membership
from db.guild_settings import get_guild_config

logger = logging.getLogger("luna-poster")

async def luna_poster_loop(bot, session, redis=None) -> None:
    await bot.wait_until_ready()
    logger.info("Luna poster loop active")

    while True:
        try:
            games = await fetch_luna_membership(session)
            # Burada normalde diff_engine çalışır, hata olmaması için sade tutuldu
            await asyncio.sleep(21600) # 6 saatte bir kontrol
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Luna loop error: {e}")
            await asyncio.sleep(600)
