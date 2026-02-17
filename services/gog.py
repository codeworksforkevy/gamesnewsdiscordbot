GOG_ENDPOINT = "https://www.gog.com/games/ajax/filtered?mediaType=game&price=free&sort=popularity"


async def fetch_gog_free(session):
    try:
        async with session.get(GOG_ENDPOINT, timeout=15) as resp:

            if resp.status != 200:
                print("GOG status:", resp.status)
                return []

            content_type = resp.headers.get("Content-Type", "")
            if "application/json" not in content_type:
                print("GOG returned non-JSON response")
                return []

            data = await resp.json()

    except Exception as e:
        print("GOG fetch error:", e)
        return []

    offers = []

    for item in data.get("products", []):

        price_data = item.get("price", {})
        is_free = price_data.get("isFree")

        if is_free:

            url = item.get("url")
            if url and not url.startswith("http"):
                url = f"https://www.gog.com{url}"

            thumbnail = item.get("image")
            if thumbnail and not thumbnail.startswith("http"):
                thumbnail = f"https:{thumbnail}"

            offers.append({
                "platform": "gog",
                "title": item.get("title", "Unknown Title"),
                "url": url,
                "thumbnail": thumbnail
            })

    print("GOG games fetched:", len(offers))
    return offers

