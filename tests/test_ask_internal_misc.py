import io

import pandas as pd
from docx import Document

from core import ask, export, internal
from core.profile import short_name
from tests.conftest import news

DF = news([
    {"company": "AP", "title": "AP เปิดโครงการใหม่ 27 โครงการ", "category": "news_pr", "sentiment": "positive",
     "published": "2026-07-10T03:00:00Z"},
    {"company": "AP", "title": "AP ลดราคาคอนโด", "category": "promotion", "sentiment": "positive",
     "published": "2026-09-10T03:00:00Z"},
    {"company": "MC", "title": "MC ขาดทุน", "category": "financial", "sentiment": "negative",
     "published": "2026-09-12T03:00:00Z"},
    {"company": "MC", "title": "ซอย MC น้ำท่วม", "category": "irrelevant", "sentiment": "negative",
     "published": "2026-09-12T03:00:00Z"},
])


def f(**kw):
    return {"companies": [], "categories": [], "sentiments": [], "keywords": [], "days": None,
            "needs_numbers": False, **kw}


def test_keyword_hit_ranks_first():
    rows = ask.retrieve(DF, f(companies=["AP"], keywords=["โครงการใหม่"]))
    assert list(rows["title"]) == ["AP เปิดโครงการใหม่ 27 โครงการ"]


def test_sentiment_filter_and_irrelevant_excluded():
    rows = ask.retrieve(DF, f(sentiments=["negative"]))
    assert list(rows["title"]) == ["MC ขาดทุน"]


def test_unknown_brand_gives_nothing_but_known_company_falls_back_to_category():
    assert ask.retrieve(DF, f(categories=["promotion"], keywords=["Shopee"])).empty
    rows = ask.retrieve(DF, f(companies=["AP"], categories=["promotion"], keywords=["โปรแรง"]))
    assert list(rows["title"]) == ["AP ลดราคาคอนโด"]


def test_internal_long_and_wide_formats():
    long_rows, problems = internal.to_long(pd.DataFrame(
        {"บริษัท": ["เรา", "AP"], "ตัวชี้วัด": ["ยอดขาย", "ยอดขาย"], "ค่า": ["1,234.5", "45%"]}))
    assert [r["value"] for r in long_rows] == [1234.5, 45.0] and not problems
    wide_rows, problems = internal.to_long(pd.DataFrame({"บริษัท": ["เรา"], "NPS": ["abc"], "ยอดขาย": [10]}))
    assert [(r["metric"], r["value"]) for r in wide_rows] == [("ยอดขาย", 10.0)] and len(problems) == 1


def test_short_name_strips_legal_words():
    assert short_name("บริษัท แม็คกรุ๊ป จำกัด (มหาชน)") == "แม็คกรุ๊ป"
    assert short_name("MC GROUP PUBLIC COMPANY LIMITED") == "MC GROUP"


def test_docx_has_clickable_citation():
    data = export.report_docx("### หัวข้อ\n- **MC** โต [[1]](https://n/1)", "รายงาน")
    doc = Document(io.BytesIO(data))
    assert any(p.style.name == "List Bullet" for p in doc.paragraphs)
    assert "https://n/1" in [r.target_ref for r in doc.part.rels.values() if r.is_external]
