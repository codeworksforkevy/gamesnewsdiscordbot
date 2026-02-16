HUMBLE_ENDPOINT = "https://www.humblebundle.com/store/api/search?sort=bestselling&filter=onsale"

async def fetch_humble_free(session):

    try:
        async with session.get(HUMBLE_ENDPOINT, timeout=15) as resp:
            if resp.status != 200:
                return []
            data = await resp.json()
    except:
        return []

    offers = []

    for item in data.get("results", []):
        if item.get("price", {}).get("is_free"):

            image = item.get("hero_image") or item.get("tile_image")

            offers.append({
                "platform": "humble",
                "title": item.get("human_name"),
                "url": item.get("product_url"),
                "thumbnail": image
            })

    return offers
