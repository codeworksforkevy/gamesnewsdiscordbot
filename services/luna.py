from bs4 import BeautifulSoup

async def fetch_luna_membership(session):
    url = "https://luna.amazon.com/"
    async with session.get(url) as r:
        html = await r.text()
    soup = BeautifulSoup(html, "html.parser")
    games = []
    for img in soup.select("img")[:6]:
        title = img.get("alt")
        if title:
            games.append({
                "title": title,
                "url": "https://luna.amazon.com/",
                "platform": "luna"
            })
    return games
