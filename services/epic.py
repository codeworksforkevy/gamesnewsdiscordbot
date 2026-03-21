# services/epic.py

import logging
import datetime as dt
import json

from services.http_utils import fetch_with_retry
from services.metrics import inc

logger = logging.getLogger("epic-service")

EPIC_ENDPOINT = (
    "https://store-site-backend-static.ak.epicgames.com/"
    "freeGamesPromotions"
)


# ==================================================
# HELPERS
# ==================================================

def _safe_get(d, *keys):
    for k in keys:
        if not isinstance(d, dict):
            return None
        d = d.get(k)
    return d


def _extract_image(images):
    if not images:
        return None

    for img in images:
        if img.get("type") == "OfferImageWide":
            return img.get("url")

    return images[0].get("url")


def _build_url(el):
    slug = el.get("productSlug") or el.get("urlSlug")

    if slug:
        return f"https://store.epicgames.com/en-US/p/{slug}"

    return "https://store.epicgames.com/"


# ==================================================
# FETCH EPIC FREE GAMES
# ==================================================

async def fetch_epic_free(session, redis=None):
    """
    Production-grade Epic free games fetcher
    """

    logger.info("[Epic] fetch start")

    try:
        text = await fetch_with_retry(session, EPIC_ENDPOINT)
        inc("epic_fetch_success")

    except Exception as e:
        inc("epic_fetch_fail")

        logger.warning(
            "Epic fetch failed",
            extra={"extra_data": {"error": str(e)}}
        )
        return []

    logger.info(f"[Epic] response size: {len(text)}")

    try:
        data = json.loads(text)
    except Exception:
        logger.warning("Epic JSON decode failed")
        return []

    elements = _safe_get(
        data,
        "data",
        "Catalog",
        "searchStore",
        "elements"
    ) or []

    now = dt.datetime.now(dt.timezone.utc)

    offers = []

    for el in elements:

        try:
            promotions = el.get("promotions")
            if not promotions:
                continue

            promo_groups = promotions.get("promotionalOffers", [])

            if not promo_groups:
                continue

            for group in promo_groups:
                for offer in group.get("promotionalOffers", []):

                    # -------------------------
                    # DATE FILTER
                    # -------------------------
                    try:
                        start = dt.datetime.fromisoformat(
                            offer["startDate"].replace("Z", "+00:00")
                        )
                        end = dt.datetime.fromisoformat(
                            offer["endDate"].replace("Z", "+00:00")
                        )
                    except Exception:
                        continue

                    if not (start <= now <= end):
                        continue

                    # -------------------------
                    # PRICE CHECK (extra safety)
                    # -------------------------
                    price = _safe_get(el, "price", "totalPrice", "discountPrice")

                    if price is not None and price != 0:
                        continue

                    # -------------------------
                    # BUILD OBJECT
                    # -------------------------
                    title = el.get("title") or "Unknown Title"

                    if not title:
                        continue

                    game = {
                        "id": f"epic-{el.get('id') or title}",
                        "title": title.strip(),
                        "platform": "Epic",
                        "url": _build_url(el),
                        "thumbnail": _extract_image(el.get("keyImages")),
                        "start_date": start.isoformat(),
                        "end_date": end.isoformat(),
                    }

                    offers.append(game)

        except Exception as e:
            logger.warning(
                "Epic item parse failed",
                extra={"extra_data": {"error": str(e)}}
            )
            continue

    # -------------------------
    # DEDUPLICATION
    # -------------------------
    unique = {}
    for g in offers:
        key = f"{g['platform']}-{g['title']}"
        unique[key] = g

    offers = list(unique.values())

    # -------------------------
    # METRICS
    # -------------------------
    inc("epic_games_found", len(offers))

    logger.info(
        "Epic games fetched",
        extra={"extra_data": {"count": len(offers)}}
    )

    return offers
