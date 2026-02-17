import datetime as dt

EPIC_ENDPOINT = "https://store-site-backend-static-ipv4.ak.epicgames.com/freeGamesPromotions"


async def fetch_epic_free(session):
    try:
        async with session.get(EPIC_ENDPOINT, timeout=15) as resp:
            if resp.status != 200:
                print("Epic API status:", resp.status)
                return []

            data = await resp.json()

    except Exception as e:
        print("Epic fetch error:", e)
        return []

    offers = []

    # 🔥 FIX: timezone-aware now
    now = dt.datetime.now(dt.timezone.utc)

    elements = (
        data.get("data", {})
        .get("Catalog", {})
        .get("searchStore", {})
        .get("elements", [])
    )

    for el in elements:
        promotions = el.get("promotions")
        if not promotions:
            continue

        promotional_groups = promotions.get("promotionalOffers", [])

        for group in promotional_groups:
            for offer in group.get("promotionalOffers", []):

                try:
                    start = dt.datetime.fromisoformat(
                        offer["startDate"].replace("Z", "+00:00")
                    )
                    end = dt.datetime.fromisoformat(
                        offer["endDate"].replace("Z", "+00:00")
                    )
                except Exception:
                    continue

                # Active free offer check
                if start <= now <= end:

                    # Thumbnail selection
                    image = None
                    for img in el.get("keyImages", []):
                        if img.get("type") == "OfferImageWide":
                            image = img.get("url")
                            break

                    if not image and el.get("keyImages"):
                        image = el["keyImages"][0].get("url")

                    # URL construction
                    slug = el.get("productSlug") or el.get("urlSlug")

                    if slug:
                        url = f"https://store.epicgames.com/en-US/p/{slug}"
                    else:
                        url = "https://store.epicgames.com/"

                    offers.append({
                        "platform": "epic",
                        "title": el.get("title", "Unknown Title"),
                        "url": url,
                        "thumbnail": image
                    })

    print("Epic games fetched:", len(offers))
    return offers
