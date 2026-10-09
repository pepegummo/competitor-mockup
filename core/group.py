"""บริษัทในเครือ: ถาม LLM ว่าบริษัท/เครือนี้มีบริษัทลูก/บริษัทร่วมอะไรบ้าง แล้วตรวจกับ SET
หุ้นที่ LLM ให้มาต้องมีอยู่จริง และผู้ถือหุ้นใหญ่ต้องเป็นคนในเครือ (บริษัทแม่หรือบริษัทในเครือด้วยกัน)
บริษัทนอกตลาดตรวจไม่ได้ ผู้ใช้ต้องติ๊กเอง"""
import json
import re

from core import llm
from core.analyze import CJK
from core.sources import SourceSkipped, set_api

GROUP_PROMPT = """For each company or corporate group below, list its most important subsidiaries and affiliates
in Thailand that a business analyst would compare separately: operating companies with their own brand or
business line. Skip pure holding/shell companies and companies that have left the group.
If the name is a group rather than one company (e.g. "CP", "PTT", "SCG"), list the group's main companies.
Give at most {n} per company, most important first.
Also give "holder_keywords": short name fragments of the group's companies as they appear in Thai shareholder
registers (Thai and English), e.g. ["ปตท", "PTT"] or ["เจริญโภคภัณฑ์", "ซี.พี.", "ซีพี"].
Return ONLY JSON:
{{"<name as given>": {{"set_symbol": "SYMBOL" or null, "holder_keywords": ["..."],
  "members": [{{"name": "<short name Thai news uses>", "aliases": ["<other names>"],
               "set_symbol": "SYMBOL" or null, "relation": "subsidiary" or "affiliate",
               "business": "<ธุรกิจหลัก ภาษาไทยสั้น ๆ>"}}]}}}}
Use "members": [] if it has no notable subsidiaries or affiliates.

Companies:
{names}"""

RELATION_TH = {"subsidiary": "บริษัทลูก", "affiliate": "บริษัทร่วม"}
_DROP = re.compile(r"บริษัท|จำกัด|\(?มหาชน\)?|public|company|limited|co\.|ltd\.?|plc|[\s.,()]", re.I)


def _norm(text):
    return _DROP.sub("", text or "").lower()


def _keywords(entry, listed):
    """คำที่ใช้จับชื่อผู้ถือหุ้นว่าเป็นคนในเครือ: จาก LLM + ชื่อจริงของหุ้นในเครือตามทะเบียน SET"""
    words = {_norm(k) for k in entry.get("holder_keywords") or [] if isinstance(k, str)}
    symbols = [entry.get("set_symbol")] + [m.get("set_symbol") for m in entry.get("members") or []]
    for sym in symbols:
        info = listed.get(str(sym or "").upper()) if listed else None
        if info:
            words |= {_norm(info["nameTH"]), _norm(info["nameEN"])}
    return {w for w in words if len(w) >= 2}


def _verify(symbol, keywords, listed):
    """คืน (ยืนยันได้ไหม, ข้อความหลักฐาน) จากผู้ถือหุ้นใหญ่ของหุ้นนี้
    ไม่นับชื่อของบริษัทนี้เอง (บางบริษัทมีชื่อตัวเองในทะเบียน เช่น หุ้นซื้อคืน)"""
    own = listed.get(symbol, {}) if listed else {}
    keywords = keywords - {_norm(own.get("nameTH")), _norm(own.get("nameEN"))}
    try:
        holders = set_api.major_shareholders(symbol)
    except SourceSkipped:
        return None, "ตรวจผู้ถือหุ้นไม่ได้ (SET ใช้ไม่ได้ตอนนี้)"
    for h in holders:
        if any(k in _norm(h["name"]) for k in keywords):
            return True, f"ผู้ถือหุ้นใหญ่: {h['name']} {h['pct']:.1f}%"
    top = holders[0] if holders else None
    return False, (f"ผู้ถือหุ้นใหญ่ไม่ใช่คนในเครือ (อันดับ 1: {top['name']} {top['pct']:.1f}%)" if top
                   else "ไม่พบข้อมูลผู้ถือหุ้น")


def find_groups(names, per_company=8):
    """1 LLM call สำหรับทุกชื่อ → {ชื่อ: {"members": [{name, aliases, set_symbol, relation, business,
    verified, evidence}]}} verified: True = ผู้ถือหุ้นใหญ่เป็นคนในเครือ, False = ไม่ใช่, None = ตรวจไม่ได้"""
    try:
        result = llm.chat_json(GROUP_PROMPT.format(n=per_company, names="\n".join(names)))
    except (json.JSONDecodeError, ValueError):
        return {}
    if not isinstance(result, dict):
        return {}
    try:
        listed = set_api.stock_list()
    except SourceSkipped:
        listed = None
    out = {}
    for name in names:
        entry = result.get(name) if isinstance(result.get(name), dict) else {}
        keywords = _keywords(entry, listed)
        parent_symbol = str(entry.get("set_symbol") or "").strip().upper()
        if not parent_symbol and listed and name.strip().upper() in listed:
            parent_symbol = name.strip().upper()
        parent_info = (listed or {}).get(parent_symbol, {})
        # ตัดชื่อที่เป็นบริษัทแม่เอง (เช่น SCB → "SCB X" คือบริษัทแม่ที่จดทะเบียนชื่อ SCB)
        members, seen = [], {_norm(name), _norm(parent_info.get("nameTH")), _norm(parent_info.get("nameEN"))} - {""}
        for m in entry.get("members") or []:
            if not isinstance(m, dict) or not str(m.get("name") or "").strip():
                continue
            mname = CJK.sub("", m["name"]).strip()  # โมเดลบางครั้งหลุดคำภาษาจีน
            symbol = str(m.get("set_symbol") or "").strip().upper()
            if listed is not None and symbol not in listed:
                symbol = ""
            if _norm(mname) in seen or (symbol and symbol == parent_symbol):
                continue
            seen.add(_norm(mname))
            if symbol:
                verified, evidence = _verify(symbol, keywords, listed)
            else:
                verified, evidence = None, "ไม่อยู่ในตลาดหลักทรัพย์ฯ ตรวจความเป็นเจ้าของไม่ได้"
            members.append({
                "name": mname, "set_symbol": symbol,
                "aliases": [a.strip() for a in m.get("aliases") or [] if isinstance(a, str) and a.strip()][:5],
                "relation": m.get("relation") if m.get("relation") in RELATION_TH else "subsidiary",
                "business": CJK.sub("", str(m.get("business") or "")).strip(),
                "verified": verified, "evidence": evidence,
            })
        out[name] = {"members": members[:per_company]}
    return out
