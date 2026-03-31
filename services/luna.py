import logging
logger = logging.getLogger("luna")

async def fetch_luna_free(session):
    # Prime Gaming ana feed'i daha stabil
    PRIME_API = "https://gaming.amazon.com/api/v1/offers"
    headers = {"User-Agent": "Mozilla/5.0"}
    
    try:
        async with session.get(PRIME_API, headers=headers) as resp:
            if resp.status != 200: return []
            data = await resp.json()
            
            results = []
            for offer in data.get("offers", []):
                # Sadece 'GAME' tipindeki bedavaları al
                if offer.get("type") != "GAME": continue
                
                # Görseli derinlemesine tara
                thumb = ""
                assets = offer.get("assets", [])
                for a in assets:
                    if a.get("purpose") in ["BOX_ART", "HERO_IMAGE"]:
                        thumb = a.get("location")
                        break

                results.append({
                    "title": offer.get("title"),
                    "url": "https://gaming.amazon.com/home",
                    "thumbnail": thumb,
                    "platform": "Luna",
                    "description": "Free with Prime Gaming"
                })
            return results
    except Exception:
        return []
