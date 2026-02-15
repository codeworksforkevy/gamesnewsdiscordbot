async def fetch_steam_discounts(session, min_discount=70):
    url = "https://store.steampowered.com/api/featuredcategories"
    async with session.get(url) as r:
        data = await r.json()
    specials = data.get("specials", {}).get("items", [])
    games = []
    for item in specials:
        if item.get("discount_percent", 0) >= min_discount:
            games.append({
                "title": item["name"],
                "discount": item["discount_percent"],
                "url": f"https://store.steampowered.com/app/{item['id']}/",
                "platform": "steam"
            })
    return games
