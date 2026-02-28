import logging
from bs4 import BeautifulSoup
from aiohttp import ClientTimeout

logger = logging.getLogger("luna-service")

LUNA_URL = "https://luna.amazon.com/"


# ==================================================
# FETCH LUNA FREE GAMES
# ==================================================

async def fetch_luna_free(session):
    """
    Fetch Amazon Luna featured / free games.
    Returns list of dicts:
        { title, thumbnail, source }
    """

    timeout = ClientTimeout(total=15)

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0 Safari/537.36"
        )
    }

    try:
        async with session.get(
            LUNA_URL,
            timeout=timeout,
            headers=headers
        ) as resp:

            if resp.status != 200:
                logger.warning(
                    "Luna non-200 response",
                    extra={"extra_data": {"status": resp.status}}
                )
                return []

            html = await resp.text()

    except Exception as e:
        logger.warning(
            "Luna fetch failed",
            extra={"extra_data": {"error": str(e)}}
        )
        return []

    soup = BeautifulSoup(html, "html.parser")

    games = []

    # ⚠ Luna DOM değişebilir — şu an img üzerinden yaklaşıyoruz
    images = soup.find_all("img")

    for img in images[:20]:

        title = img.get("alt")
        thumbnail = img.get("src")

        if not title or not thumbnail:
            continue

        title = title.strip()

        # Basit filtre: çok kısa alt text'leri alma
        if len(title) < 3:
            continue

        games.append({
            "title": title,
            "thumbnail": thumbnail,
            "source": "Amazon Luna"
        })

    logger.info(
        "Luna games fetched",
        extra={"extra_data": {"count": len(games)}}
    )

    return games
