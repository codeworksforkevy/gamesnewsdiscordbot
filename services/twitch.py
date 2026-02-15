from bs4 import BeautifulSoup
from utils.cache import cache_get, cache_set

async def fetch_twitch_badges(session):
    cache_key = "twitch_badges"
    cached = cache_get(cache_key)
    if cached:
        return cached

    url = "https://www.streamdatabase.com/twitch/global-badges"
    async with session.get(url) as r:
        html = await r.text()
    soup = BeautifulSoup(html, "html.parser")
    badges = []

    for link in soup.select("a[href*='/twitch/global-badges/']")[:10]:
        href = link.get("href")
        if not href.startswith("/twitch/global-badges/"):
            continue
        detail_url = "https://www.streamdatabase.com" + href
        async with session.get(detail_url) as d:
            detail_html = await d.text()
        detail_soup = BeautifulSoup(detail_html, "html.parser")
        title = detail_soup.find("h1")
        desc_label = detail_soup.find(string="Description")
        if title and desc_label:
            description = desc_label.find_next("p").text.strip()
            badges.append({
                "title": title.text.strip(),
                "description": description,
                "platform": "twitch"
            })

    cache_set(cache_key, badges)
    return badges
