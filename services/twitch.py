import os
from bs4 import BeautifulSoup
from utils.cache import cache_get, cache_set


# ---------------------------------------------------
# CONFIG (ENV'den alınmalı)
# ---------------------------------------------------

TWITCH_CLIENT_ID = os.getenv("TWITCH_CLIENT_ID")
TWITCH_ACCESS_TOKEN = os.getenv("TWITCH_ACCESS_TOKEN")


# ---------------------------------------------------
# 1️⃣ STREAMDATABASE SCRAPER (Title + Description)
# ---------------------------------------------------

async def fetch_twitch_badges(session):
    cache_key = "twitch_badges_streamdatabase"
    cached = cache_get(cache_key)
    if cached:
        return cached

    url = "https://www.streamdatabase.com/twitch/global-badges"

    try:
        async with session.get(url) as r:
            html = await r.text()
    except Exception:
        return []

    soup = BeautifulSoup(html, "html.parser")
    badges = []

    links = soup.select("a[href*='/twitch/global-badges/']")[:10]

    for link in links:
        href = link.get("href")

        if not href or not href.startswith("/twitch/global-badges/"):
            continue

        detail_url = "https://www.streamdatabase.com" + href

        try:
            async with session.get(detail_url) as d:
                detail_html = await d.text()
        except Exception:
            continue

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

    cache_set(cache_key, badges, ttl=1800)  # 30 dk cache
    return badges


# ---------------------------------------------------
# 2️⃣ OFFICIAL TWITCH API (Thumbnail Map)
# ---------------------------------------------------

async def fetch_official_global_badges(session):
    cache_key = "twitch_official_global_badges"
    cached = cache_get(cache_key)
    if cached:
        return cached

    if not TWITCH_CLIENT_ID or not TWITCH_ACCESS_TOKEN:
        return {}

    url = "https://api.twitch.tv/helix/chat/badges/global"

    headers = {
        "Client-ID": TWITCH_CLIENT_ID,
        "Authorization": f"Bearer {TWITCH_ACCESS_TOKEN}"
    }

    try:
        async with session.get(url, headers=headers) as r:
            if r.status != 200:
                return {}
            data = await r.json()
    except Exception:
        return {}

    badge_map = {}

    for badge in data.get("data", []):
        set_id = badge.get("set_id", "").lower()
        versions = badge.get("versions", [])

        if not versions:
            continue

        # En yüksek çözünürlük
        image_url = versions[0].get("image_url_4x")

        if image_url:
            badge_map[normalize_badge_name(set_id)] = image_url

    cache_set(cache_key, badge_map, ttl=3600)  # 1 saat cache
    return badge_map


# ---------------------------------------------------
# 3️⃣ BADGE NAME NORMALIZATION
# ---------------------------------------------------

def normalize_badge_name(name: str) -> str:
    """
    Streamdatabase title ile Twitch set_id eşleştirmesi için
    basit normalize sistemi.
    """
    if not name:
        return ""

    return (
        name.lower()
        .replace("badge", "")
        .replace("-", "")
        .replace("_", "")
        .strip()
    )

