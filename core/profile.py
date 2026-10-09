"""ข้อมูลประกอบของบริษัท: ชื่อเรียกที่สื่อใช้ (ใช้ค้นข่าว/จับข่าวจาก RSS) ชื่อหุ้นใน SET และธุรกิจหลัก"""
import json
import re

from core import llm
from core.analyze import CJK
from core.sources import SourceSkipped, set_api

PROFILE_PROMPT = """For each company below:
1. list the names Thai news media use for it: the English name, the Thai spelling,
   and common short forms or brand names. Only include names that clearly refer to that company itself,
   never names of other companies (parent, partner, operator, competitor).
   Put the most specific names first (e.g. for "AP": "AP Thailand", "เอพี (ไทยแลนด์)"), because short
   names like "AP" or "MC" also mean other things. Keep each list short (2–5 names).
2. give its stock symbol on the Stock Exchange of Thailand (SET), or null if it is not listed there
   (a listed parent company does not count).
3. "business": what it does, a short Thai phrase (e.g. "พัฒนาอสังหาริมทรัพย์ที่อยู่อาศัย").
Some lines include the official registered name from SET after " — "; that is the company meant,
so describe that company (not another company with a similar name). Use only the part before " — " as the key.
Return ONLY JSON: {{"<company as given>": {{"aliases": ["name", ...], "set_symbol": "SYMBOL" or null,
"business": "..."}}, ...}}

Companies:
{names}"""

_LEGAL = re.compile(r"บริษัท|จำกัด|\(?มหาชน\)?|public company limited|company limited|\bplc\b|\bpcl\b", re.I)


def short_name(name):
    """ตัด บริษัท/จำกัด/มหาชน ออก เหลือชื่อแบบที่สื่อใช้"""
    return " ".join(_LEGAL.sub(" ", name or "").split()).strip(" .,")


def official_names(info):
    """ชื่อตามทะเบียน SET ที่ใช้ระบุบริษัทได้แน่นอน: ชื่อไทย (เช่น "แม็คกรุ๊ป") และชื่ออังกฤษ (ตัวพิมพ์ใหญ่
    ตามทะเบียน ใช้บอก LLM เท่านั้น เพราะสื่อไม่ได้เขียนตัวใหญ่ทั้งหมด)"""
    return [n for n in (short_name(info.get("nameTH")), short_name(info.get("nameEN"))) if len(n) >= 2]


def suggest_profiles(names):
    """1 LLM call → {ชื่อ: {"aliases": [...], "set_symbol": "ADVANC" หรือ "", "business": "..."}}
    ชื่อหุ้นที่ไม่มีอยู่จริงใน SET จะถูกตัดทิ้ง ถ้า LLM ตอบไม่ผ่านคืน {} (ผู้ใช้กรอกเองได้)
    ถ้าชื่อที่พิมพ์เป็นชื่อหุ้นจริง บอกชื่อตามทะเบียน SET ให้ LLM ด้วย (กันเดาผิดบริษัท เช่น MC)
    และใส่ชื่อตามทะเบียนไว้หน้าสุดของชื่อเรียกเสมอ"""
    try:
        listed = set_api.stock_list()
    except SourceSkipped:
        listed = None  # ตรวจไม่ได้ ก็ยังเสนอชื่อหุ้นให้ผู้ใช้ตรวจเอง
    typed = {n: n.strip().upper() for n in names if listed and n.strip().upper() in listed}
    lines = [f"{n} — SET {typed[n]}: {' / '.join(official_names(listed[typed[n]]))}" if n in typed else n
             for n in names]
    try:
        result = llm.chat_json(PROFILE_PROMPT.format(names="\n".join(lines)))
    except (json.JSONDecodeError, ValueError):
        return {}
    if not isinstance(result, dict):
        return {}
    out = {}
    for name in names:
        entry = result.get(name) if isinstance(result.get(name), dict) else {}
        aliases = [a.strip() for a in entry.get("aliases") or [] if isinstance(a, str) and a.strip()]
        symbol = str(entry.get("set_symbol") or "").strip().upper()
        if listed is not None and symbol not in listed:
            symbol = ""
        if name in typed:
            symbol = typed[name]  # ผู้ใช้พิมพ์ชื่อหุ้นมาเอง (เช่น SCB ซึ่งตอนนี้เป็นหุ้นของ SCBX)
        if symbol and listed:
            aliases = official_names(listed[symbol])[:1] + aliases  # ชื่อไทยตามทะเบียนไว้หน้าสุด
        seen, clean = {name.strip().casefold()}, []
        for a in (short_name(a) for a in aliases):
            if a.casefold() not in seen:
                seen.add(a.casefold())
                clean.append(a)
        out[name] = {"aliases": clean[:5], "set_symbol": symbol,
                     "business": CJK.sub("", str(entry.get("business") or "")).strip()}
    return out
