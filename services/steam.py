import logging
from bs4 import BeautifulSoup
from aiohttp import ClientTimeout

logger = logging.getLogger("steam-service")

STEAM_FREE_URL = (
    "https://store.steampowered.com/search/?maxprice=free&specials=1"
)

STEAM_DISCOUNT_URL = (
    "https://store.steampowered.com/search/?specials=1"
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0 Safari/537.36"
    )
}


# ==================================================
# FETCH STEAM FREE GAMES
# ==================================================

async def fetch_steam_free(session):

    timeout = ClientTimeout(total=15)

    try:
        async with session.get(
            STEAM_FREE_URL,
            timeout=timeout,
            headers=HEADERS
        ) as resp:

            if resp.status != 200:
                logger.warning(
                    "Steam free non-200 response",
                    extra={"extra_data": {"status": resp.status}}
                )
                return []

            html = await resp.text()

    except Exception as e:
        logger.warning(
            "Steam free fetch failed",
            extra={"extra_data": {"error": str(e)}}
        )
        return []

    soup = BeautifulSoup(html, "html.parser")
    offers = []

    rows = soup.select(".search_result_row")

    for row in rows[:10]:

        title_el = row.select_one(".title")
        img_el = row.select_one("img")

        if not title_el:
            continue

        title = title_el.text.strip()
        url = row.get("href")
        thumbnail = img_el["src"] if img_el else None

        offers.append({
            "platform": "Steam",
            "title": title,
            "url": url,
            "thumbnail": thumbnail
        })

    logger.info(
        "Steam free games fetched",
        extra={"extra_data": {"count": len(offers)}}
    )

    return offers


# ==================================================
# FETCH STEAM DISCOUNTS
# ==================================================

async def fetch_steam_discounts(session):

    timeout = ClientTimeout(total=15)

    try:
        async with session.get(
            STEAM_DISCOUNT_URL,
            timeout=timeout,
            headers=HEADERS
        ) as resp:

            if resp.status != 200:
                logger.warning(
                    "Steam discount non-200 response",
                    extra={"extra_data": {"status": resp.status}}
                )
                return []

            html = await resp.text()

    except Exception as e:
        logger.warning(
            "Steam discount fetch failed",
            extra={"extra_data": {"error": str(e)}}
        )
        return []

    soup = BeautifulSoup(html, "html.parser")
    offers = []

    rows = soup.select(".search_result_row")

    for row in rows[:10]:

        title_el = row.select_one(".title")
        img_el = row.select_one("img")
        discount_el = row.select_one(".search_discount_pct")

        if not title_el:
            continue

        title = title_el.text.strip()
        url = row.get("href")
        thumbnail = img_el["src"] if img_el else None
        discount = (
            discount_el.text.strip()
            if discount_el else "On Sale"
        )

        offers.append({
            "platform": "Steam",
            "title": title,
            "url": url,
            "thumbnail": thumbnail,
            "discount": discount
        })

    logger.info(
        "Steam discounts fetched",
        extra={"extra_data": {"count": len(offers)}}
    )

    return offers
