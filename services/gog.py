from bs4 import BeautifulSoup

async def fetch_gog_free(session):
    url = "https://www.gog.com/en/games?priceRange=0,0"
    async with session.get(url) as r:
        html = await r.text()
    soup = BeautifulSoup(html, "html.parser")
    games = []
    for product in soup.select("product-tile")[:5]:
        title = product.get("title")
        href = product.get("href")
        if title and href:
            games.append({
                "title": title,
                "url": f"https://www.gog.com{href}",
                "platform": "gog"
            })
    return games
