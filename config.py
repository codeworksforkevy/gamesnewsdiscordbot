import os

# ==================================================
# DISCORD
# ==================================================
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")

# ==================================================
# PLATFORM BRAND COLORS (Discord embed colors)
# ==================================================
PLATFORM_COLORS = {
    "epic":   0x0E0E0E,   # Epic black
    "gog":    0x2B2B2B,   # GOG dark
    "humble": 0x6C8E7B,   # Humble green
    "twitch": 0x9146FF,   # Twitch purple
    "steam":  0x1B2838,   # Steam dark blue
    "luna":   0x00A8E1,   # Amazon Luna blue
}

# ==================================================
# POLL INTERVALS (seconds)
# ==================================================
CACHE_UPDATE_INTERVAL = 1800   # free games: 30 min
LUNA_UPDATE_INTERVAL  = 21600  # luna: 6 hours
STEAM_UPDATE_INTERVAL = 7200   # steam deals: 2 hours

# ==================================================
# STEAM DISCOUNT THRESHOLD
# Show only deals above this % discount in auto-posts
# ==================================================
STEAM_MIN_DISCOUNT = 50  # percent
