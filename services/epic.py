
import datetime as dt

EPIC_ENDPOINT = "https://store-site-backend-static-ipv4.ak.epicgames.com/freeGamesPromotions"

async def fetch_epic_free(session):
    try:
        async with session.get(EPIC_ENDPOINT, timeout=15) as resp:
            data = await resp.json()
    except:
        return []

    offers = []
    now = dt.datetime.utcnow()
    elements = data.get("data", {}).get("Catalog", {}).get("searchStore", {}).get("elements", [])

    for el in elements:
        promotions = el.get("promotions")
        if not promotions:
            continue

        for group in promotions.get("promotionalOffers", []):
            for offer in group.get("promotionalOffers", []):
                start = dt.datetime.fromisoformat(offer["startDate"].replace("Z","+00:00"))
                end = dt.datetime.fromisoformat(offer["endDate"].replace("Z","+00:00"))

                if start <= now <= end:
                    image = None
                    for img in el.get("keyImages", []):
                        if img.get("type") == "OfferImageWide":
                            image = img.get("url")
                            break
                    if not image and el.get("keyImages"):
                        image = el["keyImages"][0].get("url")

                    offers.append({
                        "platform": "epic",
                        "title": el.get("title"),
                        "url": f"https://store.epicgames.com/en-US/p/{el.get('productSlug')}",
                        "thumbnail": image
                    })
    return offers
