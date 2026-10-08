import hashlib, json, re, urllib.parse
from datetime import date

import feedparser

from core import db

RAW_DIR = db.DATA_DIR / "raw"


def fetch_news(company, lang="th", country="TH", limit=20):
    q = urllib.parse.quote(company)
    url = (f"https://news.google.com/rss/search?q={q}"
           f"&hl={lang}&gl={country}&ceid={country}:{lang}")
    feed = feedparser.parse(url)
    return [
        {"title": e.title, "url": e.link, "published": e.get("published", "")}
        for e in feed.entries[:limit]
    ]


def _safe_name(name):
    return re.sub(r'[\\/:*?"<>|]+', "_", name).strip() or "unknown"


def collect_company(company_id, company, limit=20):
    """ดึงข่าว → เก็บไฟล์ดิบ → insert documents. คืน (จำนวนที่ดึงได้, จำนวนที่เพิ่มใหม่)"""
    items = fetch_news(company, limit=limit)

    folder = RAW_DIR / _safe_name(company)
    folder.mkdir(parents=True, exist_ok=True)
    raw_path = folder / f"{date.today().isoformat()}.json"
    raw_path.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")

    added = 0
    for it in items:
        # ใส่ company_id ใน hash ด้วย ไม่งั้นข่าวที่พูดถึง 2 บริษัทพร้อมกันจะถูกนับให้แค่บริษัทแรก
        key = f"{company_id}|{it['title']}|{it['url']}"
        h = hashlib.sha256(key.encode("utf-8")).hexdigest()
        if db.insert_document(company_id, "news", it["url"], it["title"],
                              it["published"], h, str(raw_path.relative_to(db.ROOT))):
            added += 1
    return len(items), added
