import os
import time
import aiohttp
from bs4 import BeautifulSoup
from utils.cache import cache_get, cache_set


TWITCH_CLIENT_ID = os.getenv("TWITCH_CLIENT_ID")
TWITCH_CLIENT_SECRET = os.getenv("TWITCH_CLIENT_SECRET")


# ---------------------------------------------------
# 🔐 TOKEN MANAGEMENT
# ---------------------------------------------------

async def get_app_access_token(session):
    cache_key = "twitch_app_access_token"
    cached = cache_get(cache_key)

    if cached:
        token = cached.get("token")
        expires_at = cached.get("expires_at")

        if token and expires_at and time.time() < expires_at:
            return token

    # Yeni token al
    url = "https://id.twitch.tv/oauth2/token"

    payload = {
        "client_id": TWITCH_CLIENT_ID,
        "client_secret": TWITCH_CLIENT_SECRET,
        "grant_type": "client_credentials"
    }

    async with session.post(url, data=payload) as r:
        data = await r.json()

    access_token = data.get("access_token")
    expires_in = data.get("expires_in", 0)

    if not access_token:
        return None

    expires_at = time.time() + expires_in - 60  # 1 dk erken yenile

    cache_set(cache_key, {
        "token": access_token,
        "expires_at": expires_at
    }, ttl=expires_in)

    return access_token


# ---------------------------------------------------
# 📦 OFFICIAL GLOBAL BADGES (THUMBNAIL)
# ---------------------------------------------------

async def fetch_official_global_badges(session):
    cache_key = "twitch_official_global_badges"
    cached = cache_get(cache_key)
    if cached:
        return cached

    token = await get_app_access_token(session)
    if not token:
        return {}

    url = "https://api.twitch.tv/helix/chat/badges/global"

    headers = {
        "Client-ID": TWITCH_CLIENT_ID,
        "Authorization": f"Bearer {token}"
    }

    async with session.get(url, headers=headers) as r:
        if r.status != 200:
            return {}
        data = await r.json()

    badge_map = {}

    for badge in data.get("data", []):
        set_id = badge.get("set_id", "").lower()
        versions = badge.get("versions", [])

        if versions:
            image_url = versions[0].get("image_url_4x")
            if image_url:
                badge_map[normalize_badge_name(set_id)] = image_url

    cache_set(cache_key, badge_map, ttl=3600)
    return badge_map


# ---------------------------------------------------
# 📰 STREAMDATABASE SCRAPER (TEXT ONLY)
# ---------------------------------------------------

async def fetch_twitch_badges(session):
    cache_key = "twitch_badges_streamdatabase"
    cached = cache_get(cache_key)
    if cached:
        return cached

    url = "https://www.streamdatabase.com/twitch/global-badges"

    async with session.get(url) as r:
        html = await r.text()

    soup = BeautifulSoup(html, "html.parser")
    badges = []

    links = soup.select("a[href*='/twitch/global-badges/']")[:10]

    for link in links:
        href = link.get("href")
        if not href or not href.startswith("/twitch/global-badges/"):
            continue

        detail_url = "https://www.streamdatabase.com" + href

        async with session.get(detail_url) as d:
            detail_html = await d.text()

        detail_soup = BeautifulSoup(detail_html, "html.parser")

        title_tag = detail_soup.find("h1")
        desc_label = detail_soup.find(string="Description")

        if not title_tag or not desc_label:
            continue

        desc_p = desc_label.find_next("p")
        if not desc_p:
            continue

        badges.append({
            "title": title_tag.text.strip(),
            "description": desc_p.text.strip(),
            "platform": "twitch"
        })

    cache_set(cache_key, badges, ttl=1800)
    return badges


# ---------------------------------------------------
# 🧠 NORMALIZE
# ---------------------------------------------------

def normalize_badge_name(name: str) -> str:
    if not name:
        return ""

    return (
        name.lower()
        .replace("badge", "")
        .replace("-", "")
        .replace("_", "")
        .strip()
    )
