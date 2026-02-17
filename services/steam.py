from bs4 import BeautifulSoup

STEAM_URL = "https://store.steampowered.com/search/?maxprice=free&specials=1"


async def fetch_steam_free(session):
    try:
        async with session.get(STEAM_URL, timeout=15) as resp:
            if resp.status != 200:
                print("Steam status:", resp.status)
                return []
            html = await resp.text()
    except Exception as e:
        print("Steam fetch error:", e)
        return []

    soup = BeautifulSoup(html, "html.parser")
    offers = []

    rows = soup.select(".search_result_row")

    for row in rows[:10]:
        title_el = row.select_one(".title")
        img_el = row.select_one("img")

        if not title_el:
            continue

        title = title_el.text.strip()
        url = row.get("href")
        thumbnail = img_el["src"] if img_el else None

        offers.append({
            "platform": "steam",
            "title": title,
            "url": url,
            "thumbnail": thumbnail
        })

    print("Steam games fetched:", len(offers))
    return offers

