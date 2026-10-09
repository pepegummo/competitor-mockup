"""ข้อมูลภายในที่ผู้ใช้อัปโหลด (CSV / Excel) เช่น ยอดขาย ลูกค้าใหม่ NPS ส่วนแบ่งตลาด
รับได้ 2 แบบ:
  แบบยาว: คอลัมน์ บริษัท, ตัวชี้วัด, ค่า (+ หน่วย, ช่วงเวลา ไม่บังคับ)
  แบบกว้าง: คอลัมน์แรกเป็นชื่อบริษัท คอลัมน์ที่เหลือเป็นตัวชี้วัด (ตัวเลข)
เก็บไว้ใน data/app.db เครื่องนี้เท่านั้น แต่ตัวเลขจะถูกส่งให้ LLM ตอนเขียนรายงานถ้าเปิดใช้"""
import io
import re

import pandas as pd

from core import db

COLUMNS = {
    "company": ("บริษัท", "ชื่อบริษัท", "company", "name"),
    "metric": ("ตัวชี้วัด", "kpi", "metric", "รายการ"),
    "value": ("ค่า", "value", "ตัวเลข"),
    "unit": ("หน่วย", "unit"),
    "period": ("ช่วงเวลา", "งวด", "period", "ปี"),
}
SELF_WORDS = {"เรา", "บริษัทเรา", "us", "self", "ours"}

TEMPLATE = pd.DataFrame([
    {"บริษัท": "เรา", "ตัวชี้วัด": "ส่วนแบ่งตลาด", "ค่า": 45.5, "หน่วย": "%", "ช่วงเวลา": "Q2/2026"},
    {"บริษัท": "True", "ตัวชี้วัด": "ส่วนแบ่งตลาด", "ค่า": 38.0, "หน่วย": "%", "ช่วงเวลา": "Q2/2026"},
    {"บริษัท": "เรา", "ตัวชี้วัด": "NPS", "ค่า": 42, "หน่วย": "คะแนน", "ช่วงเวลา": "Q2/2026"},
    {"บริษัท": "True", "ตัวชี้วัด": "NPS", "ค่า": 35, "หน่วย": "คะแนน", "ช่วงเวลา": "Q2/2026"},
])


def _find(cols, key):
    names = {str(c).strip().lower(): c for c in cols}
    return next((names[a] for a in COLUMNS[key] if a in names), None)


def _number(x):
    """'1,234.5' / '45%' / 1234 → float หรือ None"""
    if x is None or pd.isna(x):
        return None
    if isinstance(x, (int, float)):
        return float(x)
    try:
        value = float(re.sub(r"[,\s%฿]", "", str(x)))
    except ValueError:
        return None
    return None if pd.isna(value) else value


def read_file(name, data):
    if name.lower().endswith((".xlsx", ".xls")):
        return pd.read_excel(io.BytesIO(data))
    for enc in ("utf-8-sig", "cp874"):  # cp874 = CSV ภาษาไทยจาก Excel รุ่นเก่า
        try:
            return pd.read_csv(io.BytesIO(data), encoding=enc)
        except UnicodeDecodeError:
            continue
    raise ValueError("อ่านไฟล์ไม่ได้ ลองบันทึกเป็น CSV UTF-8 หรือ .xlsx")


def to_long(df):
    """คืน [{company, metric, value, unit, period}] และรายการปัญหาที่เจอ"""
    df = df.dropna(how="all").dropna(axis=1, how="all")
    if df.empty:
        raise ValueError("ไฟล์ไม่มีข้อมูล")
    company, metric, value = (_find(df.columns, k) for k in ("company", "metric", "value"))
    unit, period = _find(df.columns, "unit"), _find(df.columns, "period")
    rows, problems = [], []
    if company and metric and value:
        for i, r in df.iterrows():
            v = _number(r[value])
            if v is None:
                problems.append(f"แถว {i + 2}: ค่า “{r[value]}” ไม่ใช่ตัวเลข")
                continue
            rows.append({"company": str(r[company]).strip(), "metric": str(r[metric]).strip(), "value": v,
                         "unit": str(r[unit]).strip() if unit and pd.notna(r[unit]) else "",
                         "period": str(r[period]).strip() if period and pd.notna(r[period]) else ""})
    else:
        first = company or df.columns[0]
        for col in df.columns:
            if col in (first, period):
                continue
            for i, r in df.iterrows():
                v = _number(r[col])
                if v is None:
                    if pd.notna(r[col]):
                        problems.append(f"แถว {i + 2} คอลัมน์ {col}: “{r[col]}” ไม่ใช่ตัวเลข")
                    continue
                rows.append({"company": str(r[first]).strip(), "metric": str(col).strip(), "value": v,
                             "unit": "", "period": str(r[period]).strip() if period and pd.notna(r[period]) else ""})
    rows = [r for r in rows if r["company"] and r["company"].lower() != "nan" and r["metric"]]
    if not rows:
        raise ValueError("ไม่พบตัวเลข ตรวจว่ามีคอลัมน์ บริษัท / ตัวชี้วัด / ค่า หรือดูไฟล์ตัวอย่าง")
    return rows, problems


def match_companies(rows, known, self_name=None):
    """จับชื่อในไฟล์กับบริษัทที่มีในระบบ (ชื่อ ชื่อเรียก ชื่อหุ้น ไม่สนตัวพิมพ์) "เรา" = บริษัทเรา
    คืน (rows ที่แก้ชื่อแล้ว, ชื่อที่จับไม่ได้)"""
    lookup = {}
    for row in db.get_companies(known):
        for alias in [row["name"], row.get("set_symbol") or ""] + row["aliases"]:
            if alias:
                lookup.setdefault(alias.strip().lower(), row["name"])
    unmatched = set()
    for r in rows:
        key = r["company"].lower()
        if key in SELF_WORDS and self_name:
            r["company"] = self_name
        elif key in lookup:
            r["company"] = lookup[key]
        else:
            unmatched.add(r["company"])
    return rows, sorted(unmatched)
