from bs4 import BeautifulSoup

LUNA_URL = "https://luna.amazon.com/"


async def fetch_luna_membership(session):
    try:
        async with session.get(LUNA_URL, timeout=15) as resp:
            if resp.status != 200:
                return []

            html = await resp.text()

    except Exception:
        return []

    soup = BeautifulSoup(html, "html.parser")
    games = []

    cards = soup.select("img")

    for img in cards[:10]:
        title = img.get("alt")
        thumbnail = img.get("src")

        if not title or not thumbnail:
            continue

        games.append({
            "platform": "luna",
            "title": title.strip(),
            "thumbnail": thumbnail,
            "url": LUNA_URL
        })

    return games
