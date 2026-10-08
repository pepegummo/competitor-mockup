"""ดึงเนื้อหาเต็มของบทความ (ใช้เมื่อเปิดตัวเลือก "ดึงเนื้อหาเต็ม")"""
from concurrent.futures import ThreadPoolExecutor

import trafilatura

MIN_CHARS = 300
MAX_CHARS = 4000


def resolve_url(url):
    """ลิงก์ Google News เป็นหน้า redirect ด้วย JavaScript ต้องถอดหา URL จริงก่อน คืน None ถ้าถอดไม่ได้"""
    if "news.google.com" not in url:
        return url
    try:
        from googlenewsdecoder import gnewsdecoder
        return gnewsdecoder(url, interval=0.5).get("decoded_url")
    except Exception:  # decoder อาศัยหน้าเว็บของ Google ที่เปลี่ยนได้ตลอด
        return None


def extract(url):
    real = resolve_url(url)
    if not real:
        return None
    html = trafilatura.fetch_url(real)
    text = trafilatura.extract(html) if html else None
    return text[:MAX_CHARS] if text else None


def fill(items, workers=4):
    """เติม content ให้รายการที่เนื้อหาสั้น (ไม่รวมรีวิว) คืนจำนวนที่ได้เนื้อหาเต็ม"""
    todo = [it for it in items if it["source_type"] != "review" and len(it.get("content") or "") < MIN_CHARS]
    if not todo:
        return 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        texts = list(pool.map(lambda it: extract(it["url"]), todo))
    got = 0
    for it, text in zip(todo, texts):
        if text and len(text) > len(it.get("content") or ""):
            it["content"] = text
            got += 1
    return got
