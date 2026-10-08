import re
import time

import feedparser
import requests
from bs4 import BeautifulSoup

from core.sources import UA, item

# ทดสอบแล้วว่าใช้ได้ (ต.ค. 2026) ส่วน bangkokbiznews, thansettakij, posttoday, mgronline ดึงไม่ได้
FEEDS = {
    "ประชาชาติธุรกิจ": "https://www.prachachat.net/feed",
    "มติชน": "https://www.matichon.co.th/feed",
    "ไทยรัฐ": "https://www.thairath.co.th/rss/news",
    "Brand Inside": "https://brandinside.asia/feed/",
    "THE STANDARD": "https://thestandard.co/feed/",
    "Blognone": "https://www.blognone.com/atom.xml",
}
CACHE_SECONDS = 600
_cache = {"at": 0, "entries": []}


def _text(html):
    return BeautifulSoup(html or "", "html.parser").get_text(" ", strip=True)


def _all_entries():
    """ดึงทุก feed ครั้งเดียวแล้วใช้ซ้ำกับทุกบริษัทภายใน 10 นาที"""
    if time.time() - _cache["at"] < CACHE_SECONDS:
        return _cache["entries"]
    entries = []
    for name, url in FEEDS.items():
        try:
            feed = feedparser.parse(requests.get(url, headers=UA, timeout=15).content)
        except requests.RequestException:
            continue
        for e in feed.entries:
            body = e.content[0].value if e.get("content") else e.get("summary", "")
            entries.append({"publisher": name, "title": e.get("title", ""), "url": e.get("link", ""),
                            "published": e.get("published", e.get("updated", "")), "text": _text(body)})
    _cache.update(at=time.time(), entries=entries)
    return entries


def _pattern(names):
    """ชื่ออังกฤษต้องตรงทั้งคำและตัวพิมพ์ (กัน 'NT' ไปตรงกับ 'ANT' หรือคำว่า true ทั่วไป) ชื่อไทยตรงแบบ substring"""
    parts = []
    for n in names:
        n = n.strip()
        if not n:
            continue
        if re.fullmatch(r"[\x00-\x7f]+", n):
            parts.append(rf"(?<![A-Za-z0-9]){re.escape(n)}(?![A-Za-z0-9])")
        else:
            parts.append(re.escape(n))
    return re.compile("|".join(parts)) if parts else None


def fetch(company, limit=20):
    pattern = _pattern([company["name"]] + company.get("aliases", []))
    out = []
    for e in _all_entries():
        if pattern.search(e["title"]) or pattern.search(e["text"]):
            out.append(item("rss", e["publisher"], e["title"], e["url"], e["published"], content=e["text"]))
        if len(out) >= limit:
            break
    return out
