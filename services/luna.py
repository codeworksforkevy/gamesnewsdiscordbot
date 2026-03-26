import logging
from typing import List, Dict, Any

logger = logging.getLogger("luna")

# ==================================================
# Amazon Luna internal API endpoint.
# This returns structured JSON — no scraping needed.
# The channel parameter targets the Prime Gaming / Luna+ catalog.
# ==================================================
LUNA_API_URL = (
    "https://api.amazon.com/luna/hapyak/api"
    "?query=contentType%3Agame"
    "&pageSize=50"
    "&channelId=PrimeGamingChannel"
)

# Fallback: Amazon Prime Gaming JSON feed (publicly accessible)
PRIME_GAMING_URL = (
    "https://gaming.amazon.com/home"
)

# Most reliable source: Prime Gaming offers API
PRIME_API_URL = (
    "https://gaming.amazon.com/graphql"
)


# ==================================================
# MAIN FETCH — Prime Gaming free games
# (Luna+ is bundled with Prime Gaming)
# ==================================================
async def fetch_luna_free(session) -> List[Dict[str, Any]]:
    """
    Fetches free games available through Amazon Prime Gaming / Luna+.
    Uses the Prime Gaming offers endpoint which returns structured JSON.
    """
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://gaming.amazon.com/",
    }

    # GraphQL query for Prime Gaming free game offers
    graphql_payload = {
        "operationName": "OffersContext",
        "variables": {
            "pageSize": 50,
            "pageIndex": 0,
            "offerType": "IN_GAME_LOOT",
        },
        "query": """
            query OffersContext($pageSize: Int, $pageIndex: Int) {
              primeOffers(pageSize: $pageSize, pageIndex: $pageIndex) {
                offers {
                  id
                  title
                  description
                  startTime
                  endTime
                  assets {
                    type
                    purpose
                    url
                    location
                    height
                    width
                  }
                  linkedJourney {
                    assets {
                      type
                      purpose
                      url
                    }
                  }
                }
              }
            }
        """,
    }

    try:
        async with session.post(
            PRIME_API_URL,
            json=graphql_payload,
            headers=headers,
            timeout=15,
        ) as resp:

            if resp.status == 200:
                data = await resp.json()
                offers = (
                    data.get("data", {})
                    .get("primeOffers", {})
                    .get("offers", [])
                )
                if offers:
                    return _parse_prime_offers(offers)

    except Exception as e:
        logger.warning(f"Prime Gaming GraphQL failed: {e}")

    # ── Fallback: scrape the free games section ────────────────────────────
    return await _fetch_luna_fallback(session, headers)


async def _fetch_luna_fallback(session, headers) -> List[Dict[str, Any]]:
    """
    Fallback fetcher — hits the Prime Gaming HTML page and extracts
    the JSON data embedded in the __NEXT_DATA__ script tag.
    This is more reliable than scraping img tags.
    """
    from bs4 import BeautifulSoup
    import json as json_mod

    try:
        async with session.get(
            "https://gaming.amazon.com/home",
            headers=headers,
            timeout=15,
        ) as resp:

            if resp.status != 200:
                logger.error(f"Prime Gaming page returned {resp.status}")
                return []

            html = await resp.text()

    except Exception as e:
        logger.error(f"Prime Gaming page fetch failed: {e}")
        return []

    soup = BeautifulSoup(html, "html.parser")

    # Amazon embeds page data in __NEXT_DATA__ script tag as JSON
    script = soup.find("script", {"id": "__NEXT_DATA__"})

    if not script or not script.string:
        logger.warning("__NEXT_DATA__ not found on Prime Gaming page")
        return _parse_images_fallback(soup)

    try:
        page_data = json_mod.loads(script.string)

        # Dig through Next.js page props to find offers
        props = page_data.get("props", {}).get("pageProps", {})
        offers_raw = (
            props.get("offers")
            or props.get("initialState", {}).get("offers", {}).get("items", [])
            or []
        )

        if offers_raw:
            results = []
            for o in offers_raw:
                title = o.get("title") or o.get("gameName") or o.get("name")
                if not title:
                    continue
                img_url = _extract_image(o)
                results.append({
                    "platform": "luna",
                    "title": title.strip(),
                    "url": "https://gaming.amazon.com/home",
                    "thumbnail": img_url,
                    "description": o.get("description", "Free with Prime Gaming"),
                })
            if results:
                return results

    except Exception as e:
        logger.warning(f"__NEXT_DATA__ parse failed: {e}")

    return _parse_images_fallback(soup)


def _parse_images_fallback(soup) -> List[Dict[str, Any]]:
    """Last resort: grab named images from the page."""
    offers = []
    seen = set()

    for img in soup.select("img[alt]"):
        title = img.get("alt", "").strip()
        src = img.get("src") or img.get("data-src", "")

        if not title or not src or title in seen:
            continue
        if len(title) < 3 or title.lower() in ("logo", "amazon", "prime"):
            continue

        seen.add(title)
        offers.append({
            "platform": "luna",
            "title": title,
            "url": "https://gaming.amazon.com/home",
            "thumbnail": src,
            "description": "Free with Prime Gaming",
        })

        if len(offers) >= 12:
            break

    return offers


def _parse_prime_offers(offers: list) -> List[Dict[str, Any]]:
    """Parse structured Prime Gaming GraphQL offer objects."""
    results = []
    for o in offers:
        title = o.get("title", "").strip()
        if not title:
            continue
        results.append({
            "platform": "luna",
            "title": title,
            "url": "https://gaming.amazon.com/home",
            "thumbnail": _extract_image(o),
            "description": o.get("description", "Free with Prime Gaming"),
            "end_time": o.get("endTime"),
        })
    return results


def _extract_image(obj: dict) -> str:
    """Pull the best image URL out of a Prime Gaming offer object."""
    for key in ("assets", "linkedJourney"):
        assets = obj.get(key, [])
        if isinstance(assets, dict):
            assets = assets.get("assets", [])
        for asset in assets or []:
            if asset.get("purpose") in ("FEATURE", "HERO", "BOXART", None):
                url = asset.get("url") or asset.get("location", "")
                if url and url.startswith("http"):
                    return url
    # Fallback to direct image fields
    for key in ("imageUrl", "image", "thumbnail", "backgroundImageUrl"):
        url = obj.get(key, "")
        if url and url.startswith("http"):
            return url
    return ""


# ==================================================
# MEMBERSHIP COMMAND (same data, kept separate
# so you can diverge later if Luna gets its own API)
# ==================================================
async def fetch_luna_membership(session) -> List[Dict[str, Any]]:
    """
    Returns Prime Gaming / Luna+ games for the /membership_exclusives command.
    """
    games = await fetch_luna_free(session)

    if not games:
        logger.warning("Luna fetch returned empty — Prime Gaming page may have changed")

    return games
