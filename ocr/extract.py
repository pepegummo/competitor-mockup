"""อ่านข้อความจาก PDF ทีละหน้า: ใช้ข้อความที่ฝังในไฟล์ก่อน ถ้าไม่มีหรือเพี้ยน (หน้าสแกน / ฟอนต์ไทย map ผิด) ค่อย OCR
ใช้ทั้งใน service ocr/app.py (container ที่มี Tesseract) และในแอปตรง ๆ เมื่อไม่ได้ตั้ง OCR_URL"""
import re

MAX_MB = 20
MAX_PAGES = 30           # ต่อการอ่าน 1 ครั้ง (ไฟล์ยาวกว่านี้ให้เลือกช่วงหน้า)
MIN_CHARS = 40           # ข้อความสั้นกว่านี้ถือว่าเป็นหน้าภาพ
DPI = 300
OCR_TIMEOUT = 60         # วินาทีต่อหน้า

_PUA = re.compile(r"[-�]")  # ฟอนต์ไทยรุ่นเก่าใน PDF มักได้ตัวอักษรกลุ่มนี้แทนสระ/วรรณยุกต์
_GOOD = re.compile(r"[฀-๿A-Za-z0-9\s.,:;()\-–%/&'\"+฿$]")
_THAI_GAP = re.compile(r"(?<=[฀-๿]) (?=[฀-๿])")


def needs_ocr(text):
    s = (text or "").strip()
    if len(s) < MIN_CHARS:
        return True
    if len(_PUA.findall(s)) > len(s) * 0.01:
        return True
    return len(_GOOD.findall(s)) < len(s) * 0.7


def _open(data):
    import fitz  # pymupdf
    if len(data) > MAX_MB * 1024 * 1024:
        raise ValueError(f"ไฟล์ใหญ่เกิน {MAX_MB} MB")
    try:
        return fitz.open(stream=data, filetype="pdf")
    except Exception as e:  # pymupdf โยน error หลายชนิดกับไฟล์เสีย
        raise ValueError("เปิดไฟล์ PDF ไม่ได้ (ไฟล์เสีย หรือมีรหัสผ่าน)") from e


def page_count(data):
    with _open(data) as doc:
        return doc.page_count


def _ocr(page):
    import pytesseract
    from PIL import Image
    pix = page.get_pixmap(dpi=DPI)
    img = Image.frombytes("RGB" if pix.n < 4 else "RGBA", (pix.width, pix.height), pix.samples)
    text = pytesseract.image_to_string(img, lang="tha+eng", timeout=OCR_TIMEOUT)
    # Tesseract แทรกช่องว่างระหว่างอักษรไทยบ่อย ภาษาไทยไม่เว้นวรรคระหว่างคำอยู่แล้ว จึงตัดได้
    return _THAI_GAP.sub("", text)


def extract_pages(data, ocr=True, first=1, last=None):
    """[{page, text, method}] method: text = ข้อความในไฟล์, ocr = อ่านจากภาพ, skipped = ต้อง OCR แต่ปิดไว้/ล้มเหลว"""
    with _open(data) as doc:
        if doc.needs_pass:
            raise ValueError("ไฟล์มีรหัสผ่าน")
        last = min(last or doc.page_count, doc.page_count)
        first = max(1, first)
        if first > last:
            raise ValueError(f"ช่วงหน้าไม่ถูกต้อง (ไฟล์มี {doc.page_count} หน้า)")
        if last - first + 1 > MAX_PAGES:
            raise ValueError(f"อ่านได้ครั้งละไม่เกิน {MAX_PAGES} หน้า (เลือก {last - first + 1} หน้า)")
        out = []
        for n in range(first, last + 1):
            page = doc[n - 1]
            text, method = page.get_text().strip(), "text"
            if needs_ocr(text):
                method = "skipped"
                if ocr:
                    try:
                        text, method = _ocr(page).strip(), "ocr"
                    except Exception:  # timeout / Tesseract ไม่มีภาษาไทย: ข้ามหน้านี้ ไม่ให้ทั้งไฟล์ล้ม
                        pass
                if method == "skipped":
                    text = ""  # ข้อความที่ได้สั้นหรือเพี้ยน ใช้ไม่ได้
            out.append({"page": n, "text": text, "method": method})
        return out
