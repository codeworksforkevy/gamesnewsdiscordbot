import logging
from aiohttp import ClientTimeout

logger = logging.getLogger("gog-service")

GOG_ENDPOINT = (
    "https://www.gog.com/games/ajax/filtered"
    "?mediaType=game&price=free&sort=popularity"
)


# ==================================================
# FETCH GOG FREE GAMES
# ==================================================

async def fetch_gog_free(session):
    """
    Fetch free games from GOG.

    Returns list of:
        {
            platform,
            title,
            url,
            thumbnail
        }
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
            GOG_ENDPOINT,
            timeout=timeout,
            headers=headers
        ) as resp:

            if resp.status != 200:
                logger.warning(
                    "GOG non-200 response",
                    extra={"extra_data": {"status": resp.status}}
                )
                return []

            content_type = resp.headers.get("Content-Type", "")

            if "application/json" not in content_type:
                logger.warning(
                    "GOG returned non-JSON response",
                    extra={"extra_data": {"content_type": content_type}}
                )
                return []

            data = await resp.json()

    except Exception as e:
        logger.warning(
            "GOG fetch failed",
            extra={"extra_data": {"error": str(e)}}
        )
        return []

    products = data.get("products")

    if not isinstance(products, list):
        logger.warning("GOG response missing products list")
        return []

    offers = []

    for item in products:

        price_data = item.get("price", {})
        is_free = price_data.get("isFree")

        if not is_free:
            continue

        url = item.get("url")
        if url and not url.startswith("http"):
            url = f"https://www.gog.com{url}"

        thumbnail = item.get("image")
        if thumbnail and not thumbnail.startswith("http"):
            thumbnail = f"https:{thumbnail}"

        offers.append({
            "platform": "GOG",
            "title": item.get("title", "Unknown Title"),
            "url": url,
            "thumbnail": thumbnail
        })

    logger.info(
        "GOG games fetched",
        extra={"extra_data": {"count": len(offers)}}
    )

    return offers
