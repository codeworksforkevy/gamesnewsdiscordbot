import logging
from typing import List, Dict, Any

logger = logging.getLogger("steam")


STEAM_API_URL = "https://store.steampowered.com/api/featuredcategories"


async def fetch_steam_discounts(session) -> List[Dict[str, Any]]:
    """
    Fetch discounted games from Steam API
    """

    try:
        async with session.get(STEAM_API_URL, timeout=10) as resp:

            if resp.status != 200:
                logger.error(f"Steam API error: {resp.status}")
                return []

            data = await resp.json()

            specials = data.get("specials", {})
            items = specials.get("items", [])

            results = []

            for item in items:
                results.append({
                    "name": item.get("name"),
                    "discount": item.get("discount_percent"),
                    "final_price": item.get("final_price"),
                    "original_price": item.get("original_price"),
                    "url": f"https://store.steampowered.com/app/{item.get('id')}"
                })

            return results

    except Exception as e:
        logger.error(f"Steam fetch failed: {e}")
        return []
