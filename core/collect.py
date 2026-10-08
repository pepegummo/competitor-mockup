import hashlib, json, re
from datetime import date

import requests

from core import db, fulltext
from core.sources import SourceSkipped, app_reviews, google_news, thai_rss, website
from core.sources.google_news import fetch_news  # noqa: F401  (discover.py ใช้)

RAW_DIR = db.DATA_DIR / "raw"

# key → (โมดูล, ชื่อที่แสดงผู้ใช้)
SOURCES = {
    "google_news": (google_news, "Google News"),
    "thai_rss": (thai_rss, "สำนักข่าวไทย"),
    "app_reviews": (app_reviews, "รีวิวแอป"),
    "website": (website, "เว็บไซต์บริษัท"),
}
SOURCE_TYPE_LABEL = {"news": "Google News", "rss": "สำนักข่าวไทย", "review": "รีวิวแอป", "website": "เว็บไซต์บริษัท"}


def _safe_name(name):
    return re.sub(r'[\\/:*?"<>|]+', "_", name).strip() or "unknown"


def _hash(company_id, it):
    # Google News ใช้รูปแบบเดิม เพื่อไม่ให้ข่าวที่เก็บไว้ก่อนหน้าถูกนับซ้ำ
    if it["source_type"] == "news":
        key = f"{company_id}|{it['title']}|{it['url']}"
    else:
        key = f"{company_id}|{it['source_type']}|{it['url']}|{it['title']}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def title_key(title):
    """ใช้จับข่าวเดียวกันจากหลายแหล่ง: ตัดชื่อสำนักข่าวท้าย ' - ...' แล้วเหลือแต่ตัวอักษร"""
    title = re.sub(r"\s+-\s+[^-]+$", "", title or "")
    return re.sub(r"[\W_]+", "", title.lower())


def collect_company(company_id, company, limit=20, sources=("google_news",), fulltext_on=False, review_limit=20):
    """ดึงจากทุกแหล่งที่เลือก → เก็บไฟล์ดิบ → insert documents
    คืน (stats, notes): stats = {ชื่อแหล่ง: (ดึงได้, ใหม่)}, notes = ข้อความที่ควรบอกผู้ใช้"""
    row = db.get_companies([company])[0]
    folder = RAW_DIR / _safe_name(company)
    folder.mkdir(parents=True, exist_ok=True)
    seen_titles = db.title_keys(company_id)
    stats, notes = {}, []

    for key in sources:
        module, label = SOURCES[key]
        try:
            items = module.fetch(row, review_limit if key == "app_reviews" else limit)
        except SourceSkipped as e:
            notes.append(f"{label}: {e}")
            continue
        except (requests.RequestException, ValueError) as e:
            notes.append(f"{label}: ดึงไม่สำเร็จ ({type(e).__name__})")
            continue

        raw_path = folder / f"{date.today().isoformat()}_{key}.json"
        raw_path.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")

        # เฉพาะรายการใหม่ และไม่ใช่ข่าวเดียวกับที่มีจากแหล่งอื่นแล้ว
        existing = db.existing_hashes([_hash(company_id, it) for it in items])
        new, dup = [], 0
        for it in items:
            if _hash(company_id, it) in existing:
                continue
            tk = title_key(it["title"])
            if it["source_type"] != "review" and tk and tk in seen_titles:
                dup += 1
                continue
            seen_titles.add(tk)
            new.append(it)

        if fulltext_on and key != "app_reviews":
            got = fulltext.fill(new)
            if new:
                notes.append(f"{label}: ได้เนื้อหาเต็ม {got}/{len(new)} รายการ")

        added = 0
        for it in new:
            if db.insert_document(company_id, it["source_type"], it["url"], it["title"], it["published"],
                                  _hash(company_id, it), str(raw_path.relative_to(db.ROOT)),
                                  it["source_name"], it["content"], it["rating"]):
                added += 1
        stats[label] = (len(items), added)
        if dup:
            notes.append(f"{label}: ข้าม {dup} ข่าวที่ซ้ำกับแหล่งอื่น")
    return stats, notes
