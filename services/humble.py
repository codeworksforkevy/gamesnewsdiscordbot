import logging
from aiohttp import ClientTimeout

logger = logging.getLogger("humble-service")
HUMBLE_ENDPOINT = "https://www.humblebundle.com/store/api/search?sort=bestselling&filter=all"

async def fetch_humble_free(session):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json"
    }
    
    try:
        async with session.get(HUMBLE_ENDPOINT, headers=headers, timeout=15) as resp:
            if resp.status != 200: return []
            data = await resp.json()
            
            results = data.get("results", [])
            offers = []
            for item in results:
                # Fiyatın tam 0 olduğundan emin ol
                price_obj = item.get("price", {})
                if price_obj.get("amount") != 0: continue
                
                image = item.get("hero_image") or item.get("tile_image")
                if image and not image.startswith("http"):
                    image = f"https:{image}"
                
                url = item.get("product_url", "")
                full_url = f"https://www.humblebundle.com{url}" if not url.startswith("http") else url

                offers.append({
                    "platform": "Humble",
                    "title": item.get("human_name", "Mystery Game"),
                    "url": full_url,
                    "thumbnail": image
                })
            return offers
    except Exception as e:
        logger.warning(f"Humble fetch error: {e}")
        return []
