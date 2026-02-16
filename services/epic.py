async def fetch_epic_free(session):

    url = "https://store-site-backend-static.ak.epicgames.com/freeGamesPromotions"

    headers = {
        "User-Agent": "Mozilla/5.0"
    }

    async with session.get(url, headers=headers) as response:
        print("Epic status:", response.status)
        data = await response.json()

    elements = data["data"]["Catalog"]["searchStore"]["elements"]

    print("Total elements:", len(elements))

    # Şimdilik filtre yapmıyoruz
    games = []

    for game in elements[:5]:
        games.append({
            "title": game.get("title"),
            "url": "https://store.epicgames.com",
            "thumbnail": None,
            "platform": "epic"
        })

    print("Returning dummy epic count:", len(games))

    return games
