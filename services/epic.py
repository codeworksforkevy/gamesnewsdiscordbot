import logging
import datetime as dt
from aiohttp import ClientTimeout

logger = logging.getLogger("epic-service")

EPIC_ENDPOINT = (
    "https://store-site-backend-static-ipv4.ak.epicgames.com/"
    "freeGamesPromotions"
)


# ==================================================
# FETCH EPIC FREE GAMES
# ==================================================

async def fetch_epic_free(session):
    """
    Fetch currently active free games from Epic Games Store.
    """

    timeout = ClientTimeout(total=15)

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0 Safari/537.36"
        ),
        "Accept": "application/json"
    }

    try:
        async with session.get(
            EPIC_ENDPOINT,
            timeout=timeout,
            headers=headers
        ) as resp:

            if resp.status != 200:
                logger.warning(
                    "Epic non-200 response",
                    extra={"extra_data": {"status": resp.status}}
                )
                return []

            data = await resp.json()

    except Exception as e:
        logger.warning(
            "Epic fetch failed",
            extra={"extra_data": {"error": str(e)}}
        )
        return []

    offers = []

    now = dt.datetime.now(dt.timezone.utc)

    try:
        elements = (
            data.get("data", {})
            .get("Catalog", {})
            .get("searchStore", {})
            .get("elements", [])
        )
    except Exception:
        logger.warning("Epic response structure unexpected")
        return []

    for el in elements:

        promotions = el.get("promotions")
        if not promotions:
            continue

        promotional_groups = promotions.get("promotionalOffers", [])

        for group in promotional_groups:
            for offer in group.get("promotionalOffers", []):

                try:
                    start = dt.datetime.fromisoformat(
                        offer["startDate"].replace("Z", "+00:00")
                    )
                    end = dt.datetime.fromisoformat(
                        offer["endDate"].replace("Z", "+00:00")
                    )
                except Exception:
                    continue

                # Active free window
                if not (start <= now <= end):
                    continue

                # Thumbnail
                image = None
                for img in el.get("keyImages", []):
                    if img.get("type") == "OfferImageWide":
                        image = img.get("url")
                        break

                if not image and el.get("keyImages"):
                    image = el["keyImages"][0].get("url")

                # URL
                slug = el.get("productSlug") or el.get("urlSlug")

                if slug:
                    url = f"https://store.epicgames.com/en-US/p/{slug}"
                else:
                    url = "https://store.epicgames.com/"

                offers.append({
                    "platform": "Epic",
                    "title": el.get("title", "Unknown Title"),
                    "url": url,
                    "thumbnail": image
                })

    # Deduplicate (safety)
    unique = {o["title"]: o for o in offers}.values()
    offers = list(unique)

    logger.info(
        "Epic games fetched",
        extra={"extra_data": {"count": len(offers)}}
    )

    return offers
