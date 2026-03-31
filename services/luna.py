import logging
from typing import List, Dict, Any

logger = logging.getLogger("luna")

async def fetch_luna_free(session) -> List[Dict[str, Any]]:
    """Amazon Prime Gaming / Luna oyunlarını çeker."""
    PRIME_API = "https://gaming.amazon.com/api/v1/offers"
    headers = {"User-Agent": "Mozilla/5.0"}
    
    try:
        async with session.get(PRIME_API, headers=headers, timeout=15) as resp:
            if resp.status != 200: return []
            data = await resp.json()
            
            results = []
            for offer in data.get("offers", []):
                if offer.get("type") != "GAME": continue
                
                thumb = ""
                for a in offer.get("assets", []):
                    if a.get("purpose") in ["BOX_ART", "HERO_IMAGE"]:
                        thumb = a.get("location")
                        break

                results.append({
                    "title": offer.get("title"),
                    "url": "https://gaming.amazon.com/home",
                    "thumbnail": thumb,
                    "platform": "Luna",
                    "end_time": offer.get("endTime")
                })
            return results
    except Exception as e:
        logger.error(f"Luna fetch failed: {e}")
        return []

async def fetch_luna_membership(session) -> List[Dict[str, Any]]:
    """Hata veren eksik fonksiyon: Poster loop ve komutlar burayı çağırır."""
    return await fetch_luna_free(session)
