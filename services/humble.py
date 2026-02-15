from bs4 import BeautifulSoup

async def fetch_humble_free(session):
    url = "https://www.humblebundle.com/store/search?price=free"
    async with session.get(url) as r:
        html = await r.text()
    soup = BeautifulSoup(html, "html.parser")
    games = []
    for item in soup.select(".entity-title")[:5]:
        title = item.text.strip()
        parent = item.find_parent("a")
        if parent:
            games.append({
                "title": title,
                "url": f"https://www.humblebundle.com{parent.get('href')}",
                "platform": "humble"
            })
    return games
