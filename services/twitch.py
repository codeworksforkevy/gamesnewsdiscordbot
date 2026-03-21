import logging
from bs4 import BeautifulSoup

TWITCH_URL = "https://www.streamdatabase.com/twitch/global-badges"
CACHE_KEY = "twitch:badges"
CACHE_TTL = 60 * 60 * 24  # 24 hours

logger = logging.getLogger("twitch-service")


async def fetch_twitch_badges(session, redis=None):
    """
    Fetch Twitch badges with Redis caching.
    """

    # ==================================================
    # CACHE CHECK
    # ==================================================
    if redis:
        try:
            cached = await redis.get(CACHE_KEY)
            if cached:
                logger.info("Twitch badges served from cache")
                return cached
        except Exception as e:
            logger.warning(f"Redis cache read failed: {e}")

    # ==================================================
    # FETCH FROM SOURCE
    # ==================================================
    try:
        async with session.get(TWITCH_URL, timeout=15) as resp:
            if resp.status != 200:
                logger.warning(f"Bad response from Twitch badge source: {resp.status}")
                return []

            html = await resp.text()

    except Exception as e:
        logger.exception(f"Twitch badge fetch failed: {e}")
        return []

    # ==================================================
    # PARSE HTML
    # ==================================================
    try:
        soup = BeautifulSoup(html, "html.parser")

        badges = []
        cards = soup.select(".card")

        for card in cards:
            title_el = card.select_one(".card-title")
            desc_el = card.select_one(".card-text")
            img_el = card.select_one("img")

            badges.append({
                "platform": "twitch",
                "title": title_el.get_text(strip=True) if title_el else "Unknown",
                "description": desc_el.get_text(strip=True) if desc_el else "",
                "thumbnail": img_el.get("src") if img_el else None
            })

        # Limit (safety)
        badges = badges[:10]

    except Exception as e:
        logger.exception(f"HTML parsing failed: {e}")
        return []

    # ==================================================
    # CACHE STORE
    # ==================================================
    if redis:
        try:
            await redis.set(CACHE_KEY, badges, ex=CACHE_TTL)
        except Exception as e:
            logger.warning(f"Redis cache write failed: {e}")

    logger.info("Twitch badges fetched successfully")
    return badges
