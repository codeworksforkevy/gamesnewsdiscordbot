HUMBLE_ENDPOINT = "https://www.humblebundle.com/store/api/search?sort=bestselling"


async def fetch_humble_free(session):
    try:
        async with session.get(HUMBLE_ENDPOINT, timeout=15) as resp:

            if resp.status != 200:
                print("Humble status:", resp.status)
                return []

            data = await resp.json()

    except Exception as e:
        print("Humble fetch error:", e)
        return []

    offers = []

    for item in data.get("results", []):

        price_data = item.get("price", {})
        amount = price_data.get("amount")

        # 🔥 Gerçek free kontrolü
        if amount == 0:

            image = item.get("hero_image") or item.get("tile_image")

            url = item.get("product_url")
            if url and not url.startswith("http"):
                url = f"https://www.humblebundle.com{url}"

            if image and not image.startswith("http"):
                image = f"https:{image}"

            offers.append({
                "platform": "humble",
                "title": item.get("human_name", "Unknown Title"),
                "url": url,
                "thumbnail": image
            })

    print("Humble games fetched:", len(offers))
    return offers

