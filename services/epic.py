async def fetch_epic_free(session):
    url = "https://store-site-backend-static.ak.epicgames.com/freeGamesPromotions"
    async with session.get(url) as r:
        data = await r.json()
    games = []
    for game in data["data"]["Catalog"]["searchStore"]["elements"]:
        promos = game.get("promotions")
        if promos and promos.get("promotionalOffers"):
            offer = promos["promotionalOffers"][0]["promotionalOffers"][0]
            if offer["discountSetting"]["discountPercentage"] == 0:
                slug = game.get("productSlug")
                if slug:
                    games.append({
                        "title": game["title"],
                        "url": f"https://store.epicgames.com/en-US/p/{slug}",
                        "platform": "epic"
                    })
    return games
