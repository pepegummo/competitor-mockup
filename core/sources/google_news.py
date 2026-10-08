import urllib.parse

import feedparser

from core.sources import item


def fetch_news(company, lang="th", country="TH", limit=20):
    q = urllib.parse.quote(company)
    url = (f"https://news.google.com/rss/search?q={q}"
           f"&hl={lang}&gl={country}&ceid={country}:{lang}")
    feed = feedparser.parse(url)
    return [
        {"title": e.title, "url": e.link, "published": e.get("published", ""),
         "publisher": e.get("source", {}).get("title", "")}
        for e in feed.entries[:limit]
    ]


def fetch(company, limit=20):
    """ข่าวล่าสุดของบริษัท + ข่าวที่ค้นด้วย "ชื่อ หัวข้อ" สำหรับหัวข้อที่ผู้ใช้สนใจ (ครึ่งหนึ่งของ limit ต่อหัวข้อ)"""
    found = fetch_news(company["name"], limit=limit)
    for topic in company.get("topics") or []:
        found += fetch_news(f"{company['name']} {topic}", limit=max(5, limit // 2))
    seen, out = set(), []
    for it in found:
        if it["url"] not in seen:
            seen.add(it["url"])
            out.append(item("news", it["publisher"], it["title"], it["url"], it["published"]))
    return out
