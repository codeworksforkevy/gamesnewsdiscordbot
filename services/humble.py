import logging
from aiohttp import ClientTimeout

logger = logging.getLogger("humble-service")

HUMBLE_ENDPOINT = (
    "https://www.humblebundle.com/store/api/search?sort=bestselling"
)


# ==================================================
# FETCH HUMBLE FREE GAMES
# ==================================================

async def fetch_humble_free(session):
    """
    Fetch free games from Humble Bundle store.

    Returns:
        [
            {
                platform,
                title,
                url,
                thumbnail
            }
        ]
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
            HUMBLE_ENDPOINT,
            timeout=timeout,
            headers=headers
        ) as resp:

            if resp.status != 200:
                logger.warning(
                    "Humble non-200 response",
                    extra={"extra_data": {"status": resp.status}}
                )
                return []

            data = await resp.json()

    except Exception as e:
        logger.warning(
            "Humble fetch failed",
            extra={"extra_data": {"error": str(e)}}
        )
        return []

    results = data.get("results")

    if not isinstance(results, list):
        logger.warning("Humble response missing results list")
        return []

    offers = []

    for item in results:

        price_data = item.get("price", {})
        amount = price_data.get("amount")

        # 🔥 Real free check
        if amount != 0:
            continue

        image = item.get("hero_image") or item.get("tile_image")

        url = item.get("product_url")
        if url and not url.startswith("http"):
            url = f"https://www.humblebundle.com{url}"

        if image and not image.startswith("http"):
            image = f"https:{image}"

        offers.append({
            "platform": "Humble",
            "title": item.get("human_name", "Unknown Title"),
            "url": url,
            "thumbnail": image
        })

    logger.info(
        "Humble games fetched",
        extra={"extra_data": {"count": len(offers)}}
    )

    return offers
