import asyncio
from bs4 import BeautifulSoup
from utils.cache import cache_get, cache_set


BASE_URL = "https://www.streamdatabase.com"


async def fetch_twitch_badges(session):
    cache_key = "twitch_badges_streamdatabase"
    cached = cache_get(cache_key)
    if cached:
        return cached

    url = f"{BASE_URL}/twitch/global-badges"

    async with session.get(url) as r:
        html = await r.text()

    soup = BeautifulSoup(html, "html.parser")

    links = [
        BASE_URL + link.get("href")
        for link in soup.select("a[href*='/twitch/global-badges/']")[:6]
        if link.get("href")
    ]

    tasks = [fetch_badge_detail(session, link) for link in links]
    results = await asyncio.gather(*tasks)

    badges = [r for r in results if r]

    cache_set(cache_key, badges, ttl=1800)

    return badges


async def fetch_badge_detail(session, detail_url):
    try:
        async with session.get(detail_url) as d:
            detail_html = await d.text()
    except Exception:
        return None

    detail_soup = BeautifulSoup(detail_html, "html.parser")

    title_tag = detail_soup.find("h1")
    desc_label = detail_soup.find(string="Description")

    if not title_tag or not desc_label:
        return None

    desc_p = desc_label.find_next("p")
    if not desc_p:
        return None

    # Badge image
    thumbnail = None
    for img in detail_soup.find_all("img"):
        src = img.get("src") or img.get("data-src")
        if src and "/wp-content/uploads/" in src:
            thumbnail = src
            break

    if thumbnail and thumbnail.startswith("/"):
        thumbnail = BASE_URL + thumbnail

    return {
        "title": title_tag.text.strip(),
        "description": desc_p.text.strip(),
        "thumbnail": thumbnail,
        "platform": "twitch"
    }
