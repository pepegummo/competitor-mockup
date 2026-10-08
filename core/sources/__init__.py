"""แหล่งข้อมูล: แต่ละโมดูลมี fetch(company, limit) คืน list ของ dict รูปแบบเดียวกัน
{source_type, source_name, title, url, published, content, rating}

company คือแถวจาก db.get_companies() (มี name, aliases, play_app_id, appstore_id, website)
"""

UA = {"User-Agent": "Mozilla/5.0 (competitor-mockup)"}


class SourceSkipped(Exception):
    """แหล่งนี้ใช้กับบริษัทนี้ไม่ได้ (ยังไม่ได้ตั้งค่า, robots.txt ไม่อนุญาต ฯลฯ) ข้อความใช้แสดงผู้ใช้"""


def item(source_type, source_name, title, url, published="", content=None, rating=None):
    return {"source_type": source_type, "source_name": source_name, "title": title, "url": url,
            "published": published, "content": content, "rating": rating}
