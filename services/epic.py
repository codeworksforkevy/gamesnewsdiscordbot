import logging
import datetime as dt
import json

from services.http_utils import fetch_with_retry
from services.metrics import inc

logger = logging.getLogger("epic-service")

EPIC_ENDPOINT = (
    "https://store-site-backend-static.ak.epicgames.com/freeGamesPromotions"
)


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


async def fetch_epic_free(session, redis=None):

    logger.info("[Epic] fetch start")

    try:
        text = await fetch_with_retry(session, EPIC_ENDPOINT)
        inc("epic_fetch_success")

    except Exception as e:
        inc("epic_fetch_fail")
        logger.warning(f"Epic fetch failed: {e}")
        return []

    try:
        data = json.loads(text)
    except Exception:
        logger.warning("Epic JSON parse failed")
        return []

    elements = _safe_get(data, "data", "Catalog", "searchStore", "elements") or []

    now = dt.datetime.now(dt.timezone.utc)

    offers = []

    for el in elements:
        try:
            promos = el.get("promotions")
            if not promos:
                continue

            for group in promos.get("promotionalOffers", []):
                for offer in group.get("promotionalOffers", []):

                    start = dt.datetime.fromisoformat(
                        offer["startDate"].replace("Z", "+00:00")
                    )
                    end = dt.datetime.fromisoformat(
                        offer["endDate"].replace("Z", "+00:00")
                    )

                    if not (start <= now <= end):
                        continue

                    title = (el.get("title") or "Unknown").strip()

                    offers.append({
                        "id": f"epic-{el.get('id')}",
                        "title": title,
                        "platform": "Epic",
                        "url": _build_url(el),
                        "thumbnail": _extract_image(el.get("keyImages")),

                        # UX
                        "description": "Limited-time free on Epic",
                        "start_date": start.isoformat(),
                        "end_date": end.isoformat(),
                    })

        except Exception as e:
            logger.warning(f"Epic parse error: {e}")

    unique = {g["title"]: g for g in offers}

    result = list(unique.values())

    inc("epic_games_found", len(result))

    logger.info(f"Epic games: {len(result)}")

    return result
