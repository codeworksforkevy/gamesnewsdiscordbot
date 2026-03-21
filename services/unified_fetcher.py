import logging

from core.event_bus import event_bus
from services.fetch_engine import RateLimiter, CircuitBreaker, safe_fetch

from services.epic import fetch_epic_free
from services.gog import fetch_gog_free
from services.steam import fetch_steam_free  # (yeni ekleyeceğiz)

logger = logging.getLogger("fetch.unified")


# ==================================================
# GLOBAL CONTROLS
# ==================================================
rate_limiter = RateLimiter(rate_per_sec=1.0)

epic_breaker = CircuitBreaker()
gog_breaker = CircuitBreaker()
steam_breaker = CircuitBreaker()


# ==================================================
# MAIN PIPELINE
# ==================================================
async def fetch_all(session):

    epic = await safe_fetch(
        "epic",
        lambda: fetch_epic_free(session),
        rate_limiter,
        epic_breaker
    )

    gog = await safe_fetch(
        "gog",
        lambda: fetch_gog_free(session),
        rate_limiter,
        gog_breaker
    )

    steam = await safe_fetch(
        "steam",
        lambda: fetch_steam_free(session),
        rate_limiter,
        steam_breaker
    )

    # merge
    games = []
    games.extend(epic or [])
    games.extend(gog or [])
    games.extend(steam or [])

    logger.info(f"Fetched total games: {len(games)}")

    # 🔥 EVENT EMIT
    await event_bus.emit("free_games_fetched", games)
