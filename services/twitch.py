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

    # 🔥 Doğru badge image bulma
    thumbnail = None

    for img in detail_soup.find_all("img"):
        src = img.get("src") or img.get("data-src")
        if not src:
            continue

        # WordPress upload klasörü badge görsellerini içerir
        if "/wp-content/uploads/" in src:
            thumbnail = src
            break

    if thumbnail and thumbnail.startswith("/"):
        thumbnail = "https://www.streamdatabase.com" + thumbnail

    return {
        "title": title_tag.text.strip(),
        "description": desc_p.text.strip(),
        "thumbnail": thumbnail,
        "platform": "twitch"
    }
