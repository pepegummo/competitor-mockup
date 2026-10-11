"""อ่านข้อความจาก PDF ที่ผู้ใช้อัปโหลด
ตั้ง OCR_URL (เช่น http://ocr:8000) = ส่งไปให้ container ocr ซึ่งมี Tesseract ภาษาไทย
ไม่ตั้ง = อ่านในแอปเอง: OCR ได้ถ้าเครื่องนี้ลง Tesseract ไว้ ไม่งั้นข้ามหน้าที่เป็นภาพ"""
import os
import shutil

import requests

from ocr.extract import MAX_PAGES, extract_pages, page_count  # noqa: F401  (MAX_PAGES / page_count ใช้ใน UI)

CHUNK_CHARS = 1500  # 1 ส่วน = 1 แถวใน documents (ถามข้อมูลได้ทีละส่วน และอ้างอิงเลขหน้าได้)


def extract(name, data, first=1, last=None):
    """[{page, text, method}] · ValueError เมื่อไฟล์ใช้ไม่ได้ (ข้อความไทย แสดงผู้ใช้ได้)"""
    url = os.environ.get("OCR_URL", "").rstrip("/")
    if not url:
        return extract_pages(data, ocr=shutil.which("tesseract") is not None, first=first, last=last)
    try:
        r = requests.post(f"{url}/extract", files={"file": (name, data, "application/pdf")},
                          data={"first": first, **({"last": last} if last else {})}, timeout=300)
    except requests.RequestException as e:
        raise ValueError(f"ติดต่อ service OCR ไม่ได้ ({url})") from e
    if r.status_code == 400:
        raise ValueError(r.json().get("detail", "อ่านไฟล์ไม่ได้"))
    r.raise_for_status()
    return r.json()["pages"]


def chunks(pages, size=CHUNK_CHARS):
    """รวมหน้าสั้นต่อกันและตัดหน้ายาว → [{first, last, text}] (ไม่รวมหน้าว่าง)"""
    out, cur = [], None
    for p in pages:
        text = " ".join((p["text"] or "").split())
        while text:
            if cur and len(cur["text"]) + 1 + len(text) > size:
                out.append(cur)
                cur = None
            if cur is None:
                cur = {"first": p["page"], "last": p["page"], "text": text[:size]}
            else:
                cur["text"] += " " + text[:size]
                cur["last"] = p["page"]
            text = text[size:]
            if text:
                out.append(cur)
                cur = None
    if cur:
        out.append(cur)
    return out
