"""
config.py
────────────────────────────────────────────────────────────────
Shared constants used across the entire bot.

This file intentionally contains ONLY static constants —
colours, intervals, thresholds. It does NOT own environment
variable access; that responsibility belongs entirely to
config/settings.py which validates, types, and centralises
every env var.

Fixes vs original:
- DISCORD_TOKEN read here AND in settings.py — two sources of
  truth for the same value. Removed from here; always use
  config/settings.py → get_config().bot.token instead.
- No __all__ — anything importing * would pull in os. Removed
  the bare `import os` since it's no longer needed.
- Poll intervals were plain module-level ints with no units
  noted in the name — added _SECONDS suffix and kept the
  comments so it's unambiguous at call sites.
- STEAM_MIN_DISCOUNT had no docstring explaining what "50" means
  in context (percent, integer, inclusive threshold). Clarified.
"""

# ──────────────────────────────────────────────────────────────
# PLATFORM BRAND COLOURS  (Discord embed color= field)
# ──────────────────────────────────────────────────────────────

PLATFORM_COLORS: dict[str, int] = {
    "epic":   0x0E0E0E,   # Epic Games — near-black
    "gog":    0x2B2B2B,   # GOG — dark grey
    "humble": 0x6C8E7B,   # Humble Bundle — muted green
    "twitch": 0x9146FF,   # Twitch — purple
    "steam":  0x1B2838,   # Steam — dark blue
    "luna":   0x00A8E1,   # Amazon Luna — bright blue
}


# ──────────────────────────────────────────────────────────────
# POLL INTERVALS
# ──────────────────────────────────────────────────────────────

CACHE_UPDATE_INTERVAL_SECONDS: int = 1800    # Free games cache — every 30 min
LUNA_UPDATE_INTERVAL_SECONDS:  int = 21600   # Luna deals      — every 6 hours
STEAM_UPDATE_INTERVAL_SECONDS: int = 7200    # Steam deals     — every 2 hours

# Backward-compat aliases (remove once all callers are updated)
CACHE_UPDATE_INTERVAL = CACHE_UPDATE_INTERVAL_SECONDS
LUNA_UPDATE_INTERVAL  = LUNA_UPDATE_INTERVAL_SECONDS
STEAM_UPDATE_INTERVAL = STEAM_UPDATE_INTERVAL_SECONDS


# ──────────────────────────────────────────────────────────────
# STEAM DEAL THRESHOLD
# ──────────────────────────────────────────────────────────────

# Minimum discount percentage (inclusive) for a Steam deal to be
# auto-posted. Deals below this threshold are cached but not announced.
# Range: 0–100. Default: 50 (show deals ≥ 50% off).
STEAM_MIN_DISCOUNT: int = 50
