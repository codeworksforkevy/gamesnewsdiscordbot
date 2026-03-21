# services/gog.py

import logging
import json

from services.http_utils import fetch_with_retry
from services.metrics import inc

logger = logging.getLogger("gog-service")

GOG_ENDPOINT = (
    "https://www.gog.com/games/ajax/filtered"
    "?mediaType=game&price=free&sort=popularity"
)


# ==================================================
# HELPERS
# ==================================================

def _safe_str(x):
    return x.strip() if isinstance(x, str) else ""


def _build_url(url):
    if not url:
        return "https://www.gog.com"

    if url.startswith("http"):
        return url

    return f"https://www.gog.com{url}"


def _build_image(img):
    if not img:
        return None

    if img.startswith("http"):
        return img

    return f"https:{img}"


# ==================================================
# FETCH GOG FREE GAMES
# ==================================================

async def fetch_gog_free(session, redis=None):
    """
    Production-grade GOG free games fetcher
    """

    logger.info("[GOG] fetch start")

    try:
        text = await fetch_with_retry(session, GOG_ENDPOINT)
        inc("gog_fetch_success")

    except Exception as e:
        inc("gog_fetch_fail")

        logger.warning(
            "GOG fetch failed",
            extra={"extra_data": {"error": str(e)}}
        )
        return []

    logger.info(f"[GOG] response size: {len(text)}")

    try:
        data = json.loads(text)
    except Exception:
        logger.warning("GOG JSON decode failed")
        return []

    products = data.get("products")

    if not isinstance(products, list):
        logger.warning("GOG response missing products list")
        return []

    offers = []

    for item in products:
        try:
            price_data = item.get("price", {})

            # -------------------------
            # FREE FILTER
            # -------------------------
            is_free = (
                price_data.get("isFree")
                or price_data.get("finalAmount") == "0.00"
            )

            if not is_free:
                continue

            title = _safe_str(item.get("title")) or "Unknown Title"

            if not title:
                continue

            game = {
                "id": f"gog-{item.get('id') or title}",
                "title": title,
                "platform": "GOG",
                "url": _build_url(item.get("url")),
                "thumbnail": _build_image(item.get("image")),
            }

            offers.append(game)

        except Exception as e:
            logger.warning(
                "GOG item parse failed",
                extra={"extra_data": {"error": str(e)}}
            )
            continue

    # -------------------------
    # DEDUP
    # -------------------------
    unique = {}
    for g in offers:
        key = f"{g['platform']}-{g['title']}"
        unique[key] = g

    offers = list(unique.values())

    # -------------------------
    # METRICS
    # -------------------------
    inc("gog_games_found", len(offers))

    logger.info(
        "GOG games fetched",
        extra={"extra_data": {"count": len(offers)}}
    )

    return offers
