import os

PROJECT_NAME = "kevkevy's gaming new bot"
GUILD_ID = 1446560723122520207

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
REDIS_URL = os.getenv("REDIS_URL")

CACHE_TTL = 1800

PLATFORM_COLORS = {
    "epic": 0x0E0E0E,
    "gog": 0x2B2B2B,
    "humble": 0x6C8E7B,
    "luna": 0xCC5500,
    "steam": 0x1B2838,
    "twitch": 0x9146FF
}
