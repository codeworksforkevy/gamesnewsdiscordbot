import logging
import json
from services.http_utils import fetch_with_retry

logger = logging.getLogger("gog-service")

GOG_ENDPOINT = "https://www.gog.com/games/ajax/filtered?mediaType=game&price=free&sort=popularity"

def _build_gog_image(img_id):
    if not img_id: return None
    if str(img_id).startswith("http"): return img_id
    # GOG'un yeni görsel formatı
    return f"https://images.gog-statics.com/{img_id}_product_tile_256_2x.webp"

async def fetch_gog_free(session, redis=None):
    logger.info("🧪 Curie is scanning GOG lab...")
    try:
        data = await fetch_with_retry(session, GOG_ENDPOINT)
        if not data or "products" not in data:
            return []
            
        offers = []
        for item in data["products"]:
            # Sadece gerçekten bedava olanları al
            price = item.get("price", {})
            if not price.get("isFree") and price.get("finalAmount") != "0.00":
                continue

            offers.append({
                "id": f"gog-{item.get('id')}",
                "title": item.get("title", "Unknown Experiment"),
                "platform": "GOG",
                "url": f"https://www.gog.com{item.get('url')}",
                "thumbnail": _build_gog_image(item.get("image")),
                "store": "GOG"
            })
        return offers
    except Exception as e:
        logger.error(f"GOG scan failed: {e}")
        return []
