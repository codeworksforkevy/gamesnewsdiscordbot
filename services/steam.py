import logging
from typing import List, Dict, Any

logger = logging.getLogger("steam")

STEAM_FEATURED_URL = "https://store.steampowered.com/api/featuredcategories"
STEAM_APP_URL      = "https://store.steampowered.com/app/{app_id}"
STEAM_CDN_URL      = "https://cdn.akamai.steamstatic.com/steam/apps/{app_id}/capsule_616x353.jpg"


# ==================================================
# PRICE FORMATTER
# ==================================================
def _format_price(cents: int, currency: str = "USD") -> str:
    """
    Convert Steam's price-in-cents to a readable string.
    Steam returns prices as integers: 999 → $9.99
    """
    if not cents:
        return "Free"
    dollars = cents / 100
    symbols = {"USD": "$", "EUR": "€", "GBP": "£"}
    symbol = symbols.get(currency, "$")
    return f"{symbol}{dollars:.2f}"


# ==================================================
# FETCH DISCOUNTED GAMES
# ==================================================
async def fetch_steam_discounts(
    session,
    min_discount: int = 0,
) -> List[Dict[str, Any]]:
    """
    Fetch discounted games from the Steam featured categories API.

    Args:
        session:      aiohttp ClientSession
        min_discount: Only return games discounted at least this % (0 = all)

    Returns list of dicts with keys:
        name, discount, final_price, original_price,
        url, thumbnail, app_id
    """
    try:
        async with session.get(
            STEAM_FEATURED_URL,
            timeout=10,
        ) as resp:

            if resp.status != 200:
                logger.error(f"Steam API returned {resp.status}")
                return []

            data = await resp.json(content_type=None)

    except Exception as e:
        logger.error(f"Steam fetch failed: {e}")
        return []

    specials = data.get("specials", {})
    items    = specials.get("items", [])

    if not items:
        logger.warning("Steam API returned no specials")
        return []

    results = []

    for item in items:

        discount = item.get("discount_percent", 0)

        # Skip items below threshold
        if discount < min_discount:
            continue

        app_id         = item.get("id")
        name           = item.get("name", "Unknown Game")
        final_cents    = item.get("final_price", 0)
        original_cents = item.get("original_price", 0)
        currency       = item.get("currency", "USD")

        # Format prices from cents → readable string
        final_str    = _format_price(final_cents, currency)
        original_str = _format_price(original_cents, currency)

        # Use Steam CDN for thumbnail (much more reliable than the API field)
        thumbnail = (
            item.get("large_capsule_image")
            or item.get("small_capsule_image")
            or (STEAM_CDN_URL.format(app_id=app_id) if app_id else "")
        )

        results.append({
            "name":           name,
            "discount":       discount,
            "final_price":    final_str,
            "original_price": original_str,
            "url":            STEAM_APP_URL.format(app_id=app_id) if app_id else "https://store.steampowered.com",
            "thumbnail":      thumbnail,
            "app_id":         app_id,
            "platform":       "steam",
        })

    # Sort by biggest discount first
    results.sort(key=lambda x: x["discount"], reverse=True)

    logger.info(f"Steam: {len(results)} discounted games fetched")
    return results


# ==================================================
# FETCH TOP FREE STEAM GAMES (bonus feature)
# ==================================================
async def fetch_steam_free(session) -> List[Dict[str, Any]]:
    """
    Fetch currently free-to-keep games from Steam's featured section.
    These are 100% discount items (truly free, not just on sale).
    """
    return await fetch_steam_discounts(session, min_discount=100)
