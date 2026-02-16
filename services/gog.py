GOG_ENDPOINT = "https://www.gog.com/games/ajax/filtered?mediaType=game&price=free&sort=popularity"

async def fetch_gog_free(session):

    try:
        async with session.get(GOG_ENDPOINT, timeout=15) as resp:
            if resp.status != 200:
                return []
            data = await resp.json()
    except:
        return []

    offers = []

    for item in data.get("products", []):
        if item.get("price", {}).get("isFree"):

            offers.append({
                "platform": "gog",
                "title": item.get("title"),
                "url": item.get("url"),
                "thumbnail": item.get("image")
            })

    return offers
