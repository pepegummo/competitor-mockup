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


MAX_ALIAS_QUERIES = 2


def alias_queries(company):
    """ชื่ออื่นที่ใช้ค้นเพิ่ม (เฉพาะที่ไม่ซ้ำกับชื่อหลักและยาวพอจะไม่กำกวม) ชื่อหลายคำใส่เครื่องหมายคำพูด"""
    main = company["name"].strip().casefold()
    out, seen = [], {main}
    for a in company.get("aliases") or []:
        a = a.strip()
        if len(a) < 4 or a.casefold() in seen:
            continue
        seen.add(a.casefold())
        out.append(f'"{a}"' if " " in a else a)
        if len(out) == MAX_ALIAS_QUERIES:
            break
    return out


def fetch(company, limit=20):
    """ข่าวล่าสุดของบริษัท (ค้นด้วยชื่อหลัก + ชื่ออื่นที่สื่อใช้) + ข่าวที่ค้นด้วย "ชื่อ หัวข้อ" ตามหัวข้อที่สนใจ
    ข่าวที่ชื่อตรงแต่เป็นเรื่องอื่น (เช่น "ซอย AP") จะถูกตัดตอนจัดหมวด (process.py)"""
    found = fetch_news(company["name"], limit=limit)
    for q in alias_queries(company):
        found += fetch_news(q, limit=max(5, limit // 2))
    for topic in company.get("topics") or []:
        found += fetch_news(f"{company['name']} {topic}", limit=max(5, limit // 2))
    seen, out = set(), []
    for it in found:
        if it["url"] not in seen:
            seen.add(it["url"])
            out.append(item("news", it["publisher"], it["title"], it["url"], it["published"]))
    return out
