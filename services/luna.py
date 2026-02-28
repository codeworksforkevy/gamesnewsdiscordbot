from bs4 import BeautifulSoup

LUNA_URL = "https://luna.amazon.com/"


# ==================================================
# LUNA FREE GAMES (Free Games System)
# ==================================================

async def fetch_luna_free(session):
    try:
        async with session.get(LUNA_URL, timeout=15) as resp:
            if resp.status != 200:
                return []

            html = await resp.text()

    except Exception:
        return []

    soup = BeautifulSoup(html, "html.parser")
    offers = []

    cards = soup.select("img")

    for img in cards[:10]:
        title = img.get("alt")
        thumbnail = img.get("src")

        if not title or not thumbnail:
            continue

        offers.append({
            "platform": "luna",
            "title": title.strip(),
            "url": LUNA_URL,
            "thumbnail": thumbnail
        })

    return offers


# ==================================================
# LUNA MEMBERSHIP (Membership Command)
# ==================================================

async def fetch_luna_membership(session):
    # Şimdilik free ile aynı veriyi döndürüyoruz
    # İstersen sonra membership-only logic ayırabiliriz
    return await fetch_luna_free(session)
