import asyncio
from bs4 import BeautifulSoup
from utils.cache import cache_get, cache_set


async def fetch_twitch_badges(session):
    cache_key = "twitch_badges_streamdatabase"
    cached = cache_get(cache_key)
    if cached:
        return cached

    base_url = "https://www.streamdatabase.com"
    url = f"{base_url}/twitch/global-badges"

    async with session.get(url) as r:
        html = await r.text()

    soup = BeautifulSoup(html, "html.parser")

    links = [
        base_url + link.get("href")
        for link in soup.select("a[href*='/twitch/global-badges/']")[:6]
        if link.get("href")
    ]

    # 🔥 Paralel detail fetch
    tasks = [fetch_badge_detail(session, link) for link in links]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    badges = []

    for result in results:
        if isinstance(result, dict):
            badges.append(result)

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

    # Thumbnail
    img_tag = detail_soup.find("img")

    thumbnail = None
    if img_tag:
        thumbnail = img_tag.get("src") or img_tag.get("data-src")

        if thumbnail and thumbnail.startswith("/"):
            thumbnail = "https://www.streamdatabase.com" + thumbnail

    return {
        "title": title_tag.text.strip(),
        "description": desc_p.text.strip(),
        "thumbnail": thumbnail,
        "platform": "twitch"
    }

