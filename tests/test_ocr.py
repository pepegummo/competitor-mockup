import shutil

import pytest

from core import analyze
from core import ocr as reader
from ocr import extract

fitz = pytest.importorskip("fitz")


def make_pdf(pages):
    """pages = ข้อความต่อหน้า ("" = หน้าว่าง เหมือนหน้าสแกน)"""
    doc = fitz.open()
    for text in pages:
        page = doc.new_page()
        if text:
            page.insert_textbox(fitz.Rect(50, 50, 550, 800), text, fontsize=10)
    data = doc.tobytes()
    doc.close()
    return data


LONG = "Quarterly sales grew 12 percent driven by the new fibre package and lower churn. " * 3


def test_text_pages_and_skipped_scans():
    pages = extract.extract_pages(make_pdf([LONG, ""]), ocr=False)
    assert [p["method"] for p in pages] == ["text", "skipped"]
    assert "fibre package" in pages[0]["text"]
    assert pages[1]["text"] == ""


def test_page_range_and_limits():
    data = make_pdf([LONG] * 3)
    assert extract.page_count(data) == 3
    assert [p["page"] for p in extract.extract_pages(data, ocr=False, first=2, last=3)] == [2, 3]
    with pytest.raises(ValueError):
        extract.extract_pages(data, ocr=False, first=3, last=2)
    with pytest.raises(ValueError):
        extract.extract_pages(b"not a pdf", ocr=False)


def test_too_many_pages(monkeypatch):
    monkeypatch.setattr(extract, "MAX_PAGES", 2)
    with pytest.raises(ValueError):
        extract.extract_pages(make_pdf([LONG] * 3), ocr=False)


def test_needs_ocr():
    assert extract.needs_ocr("")
    assert extract.needs_ocr("short")
    assert not extract.needs_ocr("ยอดขายไตรมาสนี้เพิ่มขึ้นร้อยละ 12 จากแพ็กเกจไฟเบอร์ใหม่ และลูกค้ายกเลิกน้อยลง")
    # ฟอนต์ไทยที่ map ผิดใน PDF: ได้ตัวอักษร Private Use Area แทนสระ/วรรณยุกต์
    assert extract.needs_ocr("ยอดขายไตรมาสนี้เพิ่มขึ้นร้อยละ 12 จากแพ็กเกจไฟเบอร์ใหม่ และลูกค้า")


def test_chunks_merge_and_split():
    pages = [{"page": 1, "text": "a" * 100, "method": "text"}, {"page": 2, "text": "b" * 100, "method": "text"},
             {"page": 3, "text": "", "method": "skipped"}, {"page": 4, "text": "c" * 2500, "method": "ocr"}]
    out = reader.chunks(pages, size=1000)
    assert [(c["first"], c["last"]) for c in out] == [(1, 2), (4, 4), (4, 4), (4, 4)]
    assert out[0]["text"].startswith("a" * 100 + " " + "b" * 100)
    assert sum(len(c["text"].replace(" ", "")) for c in out) == 2700


def test_save_pdf_dedup(tmp_db, monkeypatch):
    monkeypatch.delenv("OCR_URL", raising=False)
    from core import internal
    data = make_pdf([LONG, LONG, ""])
    res = internal.save_pdf("AIS", "report.pdf", data)
    assert res["added"] == 1 and res["text"] == 2 and res["skipped"] == 1
    assert internal.save_pdf("AIS", "report.pdf", data)["added"] == 0
    docs = tmp_db.uploaded_documents()
    assert docs.iloc[0]["source_name"] == "report.pdf" and docs.iloc[0]["company"] == "AIS"
    assert tmp_db.delete_uploaded("report.pdf", "AIS") == 1
    assert tmp_db.uploaded_documents().empty


def test_uploaded_docs_not_counted_as_news():
    import pandas as pd
    df = pd.DataFrame({"source_type": ["news", "review", "document", "set"]})
    assert list(analyze.news_only(df)["source_type"]) == ["news", "set"]


def test_link_refs_upload_is_plain_text():
    refs = [("ข่าว", "https://example.com/a"), ("report.pdf · หน้า 3", "upload://abc#page=3")]
    out = analyze.link_refs("ยอดขายโต [1] และลูกค้าใหม่ [2]", refs)
    assert "[[1]](https://example.com/a)" in out
    assert "upload://" not in out
    assert "2. report.pdf · หน้า 3" in out


@pytest.mark.skipif(not shutil.which("tesseract"), reason="ไม่ได้ลง Tesseract")
def test_ocr_scanned_page():
    doc = fitz.open()
    page = doc.new_page()
    page.insert_textbox(fitz.Rect(50, 50, 550, 800), LONG, fontsize=14)
    pix = page.get_pixmap(dpi=200)
    scan = fitz.open()
    scan.new_page().insert_image(scan[0].rect, stream=pix.tobytes("png"))
    pages = extract.extract_pages(scan.tobytes(), ocr=True)
    assert pages[0]["method"] == "ocr" and "fibre" in pages[0]["text"].lower()
