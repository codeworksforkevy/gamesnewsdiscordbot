
from bs4 import BeautifulSoup

TWITCH_URL = "https://www.streamdatabase.com/twitch/global-badges"

async def fetch_twitch_badges(session):
    try:
        async with session.get(TWITCH_URL, timeout=15) as resp:
            html = await resp.text()
    except:
        return []

    soup = BeautifulSoup(html, "html.parser")
    badges = []

    cards = soup.select(".card")
    for card in cards[:10]:
        title = card.select_one(".card-title")
        desc = card.select_one(".card-text")
        img = card.select_one("img")

        badges.append({
            "platform": "twitch",
            "title": title.text.strip() if title else "Unknown",
            "description": desc.text.strip() if desc else "",
            "thumbnail": img["src"] if img else None
        })

    return badges
