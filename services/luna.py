from bs4 import BeautifulSoup

LUNA_URL = "https://gaming.amazon.com/home"


async def fetch_luna_free(session):
    try:
        async with session.get(LUNA_URL, timeout=15) as resp:
            if resp.status != 200:
                print("Luna status:", resp.status)
                return []
            html = await resp.text()
    except Exception as e:
        print("Luna fetch error:", e)
        return []

    soup = BeautifulSoup(html, "html.parser")
    offers = []

    # Amazon DOM çok değişken olduğu için geniş selector
    cards = soup.find_all("img")

    for img in cards:
        alt = img.get("alt")
        src = img.get("src")

        if not alt or not src:
            continue

        if "game" in alt.lower():
            offers.append({
                "platform": "luna",
                "title": alt.strip(),
                "url": LUNA_URL,
                "thumbnail": src
            })

    print("Luna games fetched:", len(offers))
    return offers

