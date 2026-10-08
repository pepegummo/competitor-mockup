from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup

from core.sources import UA, SourceSkipped, item

# ลิงก์เมนูมักสั้น ("บริการ", "โปรโมชัน") หัวข้อบทความยาวกว่านี้
MIN_TITLE = 25


def _allowed(url):
    try:
        r = requests.get(urljoin(url, "/robots.txt"), headers=UA, timeout=10)
    except requests.RequestException:
        return True
    if r.status_code != 200:
        return True
    rp = RobotFileParser()
    rp.parse(r.text.splitlines())
    return rp.can_fetch(UA["User-Agent"], url)


def _host(url):
    return urlparse(url).netloc.lower().removeprefix("www.")


def fetch(company, limit=20):
    """ดึงลิงก์บทความจากหน้า newsroom/โปรโมชันของบริษัท (เว็บที่โหลดด้วย JavaScript ล้วนจะได้ 0 รายการ)"""
    url = company.get("website")
    if not url:
        raise SourceSkipped("ยังไม่ได้ใส่ URL เว็บไซต์")
    if not _allowed(url):
        raise SourceSkipped("robots.txt ของเว็บไม่อนุญาตให้ดึง")
    soup = BeautifulSoup(requests.get(url, headers=UA, timeout=20).text, "html.parser")
    # เมนูของเว็บไม่ใช่บทความ (header ตัดเฉพาะที่มีเมนูอยู่ข้างใน เพราะการ์ดบทความก็ใช้ <header> ได้)
    for tag in soup.find_all(["nav", "footer"]) + [h for h in soup.find_all("header") if h.find("nav")]:
        tag.decompose()
    domain = _host(url)
    base_path = urlparse(url).path.rstrip("/")
    links, seen = [], {url.rstrip("/")}
    for a in soup.find_all("a", href=True):
        text = a.get_text(" ", strip=True)
        href = urljoin(url, a["href"]).split("#")[0]
        if len(text) < MIN_TITLE or href.rstrip("/") in seen or not _host(href).endswith(domain):
            continue
        seen.add(href.rstrip("/"))
        links.append((text, href))
    # ถ้ามีลิงก์ที่อยู่ใต้ path ของหน้าที่ให้มา (เช่น /newsroom/...) ใช้เฉพาะกลุ่มนั้น จะได้บทความไม่ใช่เมนู
    under = [(t, h) for t, h in links if base_path and urlparse(h).path.startswith(base_path + "/")]
    out = [item("website", domain, t, h) for t, h in (under or links)[:limit]]
    if not out:
        raise SourceSkipped("ไม่พบลิงก์บทความในหน้า (เว็บอาจโหลดด้วย JavaScript)")
    return out
