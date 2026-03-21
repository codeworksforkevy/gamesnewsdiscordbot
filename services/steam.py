import aiohttp


async def fetch_steam_free(session):
    url = "https://store.steampowered.com/api/featuredcategories"

    async with session.get(url, timeout=10) as resp:
        data = await resp.json()

    games = []

    # Basit extraction (örnek)
    for item in data.get("specials", {}).get("items", []):
        if item.get("final_price") == 0:
            games.append({
                "title": item.get("name"),
                "url": item.get("store_url"),
                "platform": "Steam"
            })

    return games
