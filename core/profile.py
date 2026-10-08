"""ข้อมูลประกอบของบริษัท: ชื่อเรียกที่สื่อใช้ (ใช้จับข่าวจาก RSS) และชื่อหุ้นใน SET"""
import json

from core import llm
from core.sources import SourceSkipped, set_api

PROFILE_PROMPT = """For each company below:
1. list the names Thai news media use for it: the English name, the Thai spelling,
   and common short forms or brand names. Only include names that clearly refer to that company.
   Keep each list short (2–5 names).
2. give its stock symbol on the Stock Exchange of Thailand (SET), or null if it is not listed there
   (a listed parent company does not count).
Return ONLY JSON: {{"<company as given>": {{"aliases": ["name", ...], "set_symbol": "SYMBOL" or null}}, ...}}

Companies:
{names}"""


def suggest_profiles(names):
    """1 LLM call → {ชื่อ: {"aliases": [...], "set_symbol": "ADVANC" หรือ ""}}
    ชื่อหุ้นที่ไม่มีอยู่จริงใน SET จะถูกตัดทิ้ง ถ้า LLM ตอบไม่ผ่านคืน {} (ผู้ใช้กรอกเองได้)"""
    try:
        result = llm.chat_json(PROFILE_PROMPT.format(names="\n".join(names)))
    except (json.JSONDecodeError, ValueError):
        return {}
    if not isinstance(result, dict):
        return {}
    try:
        listed = set_api.stock_list()
    except SourceSkipped:
        listed = None  # ตรวจไม่ได้ ก็ยังเสนอชื่อหุ้นให้ผู้ใช้ตรวจเอง
    out = {}
    for name in names:
        entry = result.get(name) if isinstance(result.get(name), dict) else {}
        aliases = [a.strip() for a in entry.get("aliases") or [] if isinstance(a, str) and a.strip()][:5]
        symbol = str(entry.get("set_symbol") or "").strip().upper()
        if listed is not None and symbol not in listed:
            symbol = ""
        out[name] = {"aliases": aliases, "set_symbol": symbol}
    return out
