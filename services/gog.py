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


def _extract_price(price_data):
    """
    Normalize price info (UX improvement)
    """
    if not isinstance(price_data, dict):
        return {}

    return {
        "is_free": bool(
            price_data.get("isFree") or price_data.get("finalAmount") == "0.00"
        ),
        "final": price_data.get("finalAmount"),
        "currency": price_data.get("currency")
    }


# ==================================================
# FETCH GOG FREE GAMES
# ==================================================

async def fetch_gog_free(session, redis=None):

    logger.info("[GOG] fetch start")

    # -------------------------
    # FETCH WITH RETRY
    # -------------------------
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

    # -------------------------
    # DEBUG LOG
    # -------------------------
    logger.info(
        "[GOG] response size",
        extra={"extra_data": {"size": len(text)}}
    )

    # -------------------------
    # JSON PARSE SAFE
    # -------------------------
    try:
        data = json.loads(text)
    except Exception as e:
        logger.warning(
            "GOG JSON decode failed",
            extra={"extra_data": {"error": str(e)}}
        )
        return []

    # -------------------------
    # VALIDATION
    # -------------------------
    products = data.get("products")

    if not isinstance(products, list):
        logger.warning("GOG response missing products list")
        return []

    offers = []

    # -------------------------
    # PARSE PRODUCTS
    # -------------------------
    for item in products:

        try:
            price_data = _extract_price(item.get("price"))

            # -------------------------
            # FREE FILTER
            # -------------------------
            if not price_data.get("is_free"):
                continue

            title = _safe_str(item.get("title"))

            if not title:
                continue

            game = {
                "id": f"gog-{item.get('id') or title}",
                "title": title,
                "platform": "GOG",
                "url": _build_url(item.get("url")),
                "thumbnail": _build_image(item.get("image")),

                # UX ENHANCEMENT
                "price": "Free",
                "currency": price_data.get("currency"),
                "expires": None,  # GOG genelde expiry vermez
                "store": "GOG"
            }

            offers.append(game)

        except Exception as e:
            logger.warning(
                "GOG item parse failed",
                extra={"extra_data": {"error": str(e)}}
            )
            continue

    # -------------------------
    # DEDUP (LOCAL SAFETY)
    # -------------------------
    unique = {}

    for g in offers:
        key = g["title"]

        if key not in unique:
            unique[key] = g

    offers = list(unique.values())

    # -------------------------
    # METRICS
    # -------------------------
    inc("gog_games_found", len(offers))

    # -------------------------
    # FINAL LOG
    # -------------------------
    logger.info(
        "GOG games fetched",
        extra={"extra_data": {"count": len(offers)}}
    )

    return offers
