import os
import asyncio
from bs4 import BeautifulSoup
from utils.cache import cache_get, cache_set


BASE_URL = "https://www.streamdatabase.com"

TWITCH_CLIENT_ID = os.getenv("TWITCH_CLIENT_ID")
TWITCH_CLIENT_SECRET = os.getenv("TWITCH_CLIENT_SECRET")


# ---------------------------------------------------
# 🔐 TOKEN AUTO REFRESH
# ---------------------------------------------------

async def get_app_access_token(session):
    cache_key = "twitch_app_token"
    cached = cache_get(cache_key)

    if cached:
        return cached

    url = "https://id.twitch.tv/oauth2/token"

    payload = {
        "client_id": TWITCH_CLIENT_ID,
        "client_secret": TWITCH_CLIENT_SECRET,
        "grant_type": "client_credentials"
    }

    async with session.post(url, data=payload) as r:
        data = await r.json()

    token = data.get("access_token")
    expires = data.get("expires_in", 3600)

    if token:
        cache_set(cache_key, token, ttl=expires - 60)

    return token


# ---------------------------------------------------
# 🟣 OFFICIAL TWITCH BADGES (THUMBNAIL)
# ---------------------------------------------------

async def fetch_official_global_badges(session):
    cache_key = "twitch_global_badges_official"
    cached = cache_get(cache_key)
    if cached:
        return cached

    token = await get_app_access_token(session)
    if not token:
        return {}

    headers = {
        "Client-ID": TWITCH_CLIENT_ID,
        "Authorization": f"Bearer {token}"
    }

    url = "https://api.twitch.tv/helix/chat/badges/global"

    async with session.get(url, headers=headers) as r:
        if r.status != 200:
            return {}
        data = await r.json()

    badge_map = {}

    for badge in data.get("data", []):
        set_id = badge.get("set_id")
        versions = badge.get("versions", [])

        if versions:
            badge_map[set_id.lower()] = versions[0].get("image_url_4x")

    cache_set(cache_key, badge_map, ttl=3600)

    return badge_map


# ---------------------------------------------------
# 📰 STREAMDATABASE TEXT SCRAPER
# ---------------------------------------------------

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

    soup = BeautifulSoup(detail_html, "html.parser")

    title_tag = soup.find("h1")
    desc_label = soup.find(string="Description")

    if not title_tag or not desc_label:
        return None

    desc_p = desc_label.find_next("p")
    if not desc_p:
        return None

    return {
        "title": title_tag.text.strip(),
        "description": desc_p.text.strip()
    }
