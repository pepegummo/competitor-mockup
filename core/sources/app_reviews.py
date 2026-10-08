import re
import time
from datetime import datetime

import requests
from google_play_scraper import Sort, app as play_app, reviews as play_reviews_api

from core.sources import UA, SourceSkipped, item


def appstore_reviews(app_id, limit=20):
    url = f"https://itunes.apple.com/th/rss/customerreviews/page=1/id={app_id}/sortby=mostrecent/json"
    entries = []
    for attempt in range(2):  # endpoint นี้บางครั้งตอบ feed ว่าง ลองใหม่ 1 ครั้ง
        entries = requests.get(url, headers=UA, timeout=20).json().get("feed", {}).get("entry", [])
        if entries:
            break
        time.sleep(1.5)
    if isinstance(entries, dict):  # มีรีวิวเดียวจะได้ dict แทน list
        entries = [entries]
    out = []
    for e in entries:
        if "im:rating" not in e:  # บางครั้งรายการแรกเป็นข้อมูลแอป ไม่ใช่รีวิว
            continue
        text = e.get("content", {}).get("label", "")
        review_id = e.get("id", {}).get("label", "")
        out.append(item("review", "App Store", e.get("title", {}).get("label") or text[:60],
                        f"https://apps.apple.com/th/app/id{app_id}#review-{review_id}",
                        e.get("updated", {}).get("label", ""), content=text,
                        rating=int(e["im:rating"]["label"])))
        if len(out) >= limit:
            break
    return out


def play_reviews(app_id, limit=20):
    rows, _ = play_reviews_api(app_id, lang="th", country="th", sort=Sort.NEWEST, count=limit)
    return [item("review", "Google Play", (r["content"] or "")[:60],
                 f"https://play.google.com/store/apps/details?id={app_id}&reviewId={r['reviewId']}",
                 r["at"].isoformat() if isinstance(r["at"], datetime) else "", content=r["content"],
                 rating=r["score"])
            for r in rows]


def fetch(company, limit=20):
    if not company.get("appstore_id") and not company.get("play_app_id"):
        raise SourceSkipped("ยังไม่ได้ตั้งค่าแอป")
    out = []
    if company.get("appstore_id"):
        out += appstore_reviews(company["appstore_id"], limit)
    if company.get("play_app_id"):
        out += play_reviews(company["play_app_id"], limit)
    return out


def search_apps(name):
    """หาแอปที่น่าจะใช่จากชื่อบริษัท คืน dict ที่อาจมี appstore_id/appstore_name/play_app_id/play_name"""
    found = {}
    try:
        res = requests.get("https://itunes.apple.com/search", headers=UA, timeout=15, params={
            "term": name, "country": "th", "entity": "software", "limit": 1}).json().get("results", [])
        if res:
            found.update(appstore_id=str(res[0]["trackId"]), appstore_name=res[0]["trackName"])
    except (requests.RequestException, ValueError):
        pass
    try:
        # google-play-scraper ทิ้ง appId ของผลแรก (ซึ่งมักเป็นแอปที่ถูก) จึงอ่าน id จากหน้าค้นหาเอง
        # และค้นด้วยชื่อแอปบน App Store ถ้ามี (เช่น "myAIS" ได้แอปที่ตรงกว่าค้นคำว่า "AIS")
        query = found.get("appstore_name") or name
        html = requests.get("https://play.google.com/store/search", headers=UA, timeout=20,
                            params={"q": query, "c": "apps", "hl": "th", "gl": "TH"}).text
        ids = list(dict.fromkeys(re.findall(r"/store/apps/details\?id=([\w.]+)", html)))
        if ids:
            found["play_app_id"] = ids[0]
            try:
                found["play_name"] = play_app(ids[0], lang="th", country="th")["title"]
            except Exception:  # ไม่ได้ชื่อก็ยังใช้ id ได้
                found["play_name"] = ids[0]
    except requests.RequestException:
        pass
    return found
