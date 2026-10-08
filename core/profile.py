"""ข้อมูลประกอบของบริษัท: ชื่อเรียกที่สื่อใช้ (ใช้จับข่าวจาก RSS)"""
import json

from core import llm

ALIAS_PROMPT = """For each company below, list the names Thai news media use for it:
the English name, the Thai spelling, and common short forms or brand names.
Only include names that clearly refer to that company. Keep each list short (2–5 names).
Return ONLY JSON: {{"<company as given>": ["name", ...], ...}}

Companies:
{names}"""


def suggest_aliases(names):
    """1 LLM call → {ชื่อ: [ชื่อเรียก, ...]} ถ้า LLM ตอบไม่ผ่านคืน {} (ผู้ใช้กรอกเองได้)"""
    try:
        result = llm.chat_json(ALIAS_PROMPT.format(names="\n".join(names)))
    except (json.JSONDecodeError, ValueError):
        return {}
    if not isinstance(result, dict):
        return {}
    return {name: [a.strip() for a in result.get(name, []) if isinstance(a, str) and a.strip()][:5]
            for name in names}
