"""Phase 3: หาคู่แข่งจาก 2 ทาง (ถาม LLM + ดึงชื่อจากข่าว) → รวมชื่อซ้ำ → ตรวจหลักฐาน → จัดอันดับ"""
import json
import re

from core import llm
from core.collect import fetch_news

LLM_PROMPT = """List up to {n} direct competitors of "{company}" in {country}.
Industry hint: {industry}.
Return ONLY JSON: [{{"name": "...", "reason": "<เหตุผลภาษาไทย 1 ประโยค>"}}]
If you do not know this company, return []."""

EXTRACT_PROMPT = """Below are news headlines related to "{company}"{industry_part}.
List the other companies in these headlines that are DIRECT competitors of "{company}":
they sell the same kind of products or services to the same customers.
Do NOT include partners, suppliers, customers, content or app providers, TV channels, government agencies,
"{company}" itself or its subsidiaries, or news publishers
(the text after the last " - " in each headline is usually the publisher).
Return ONLY JSON: [{{"name": "...", "headline_ids": [<id>, ...]}}]
Return [] if there are none.

Headlines:
{lines}"""

MERGE_PROMPT = """Our company is "{company}". Below are candidate competitor names. Some may be
duplicates, abbreviations, or Thai/English versions of the same company.
1. Group names that refer to the same company, including brands of the same corporate group
   (a parent company and its brands or subsidiaries go in one group). Use the short name people
   commonly use for the group as "name".
2. Leave out "{company}" itself and companies in the same group as "{company}" (parent or subsidiaries).
Return ONLY JSON: [{{"name": "...", "members": ["<input name>", ...]}}]
Use the input names exactly as written in "members".

Names:
{names}"""

_SUFFIX = re.compile(
    r"บริษัท|บมจ\.?|จำกัด|\(มหาชน\)|มหาชน|public company limited|\bpcl\b|co\.?,?\s*ltd\.?|"
    r"\blimited\b|\binc\.?|\bcorp(oration)?\.?|\bgroup\b", re.I)


def clean_name(name):
    """ตัดวงเล็บท้ายชื่อ เช่น 'NT (National Telecom)' → 'NT' เพื่อให้ค้นข่าวเจอ"""
    return re.sub(r"\s*[(（].*?[)）]", "", name).strip() or name.strip()


def norm(name):
    """ทำชื่อให้อยู่รูปเดียวกันเพื่อเทียบชื่อซ้ำ เช่น 'True Corporation PCL' → 'true'"""
    return re.sub(r"[\W_]+", "", _SUFFIX.sub(" ", name.lower()))


def _is_self(name, company):
    n, c = norm(name), norm(company)
    return not n or n == c or (len(c) >= 3 and c in n)


def _named_list(result, *keys):
    """ตรวจว่า LLM ตอบเป็น list ของ dict ที่มี name; คืนเฉพาะรายการที่ใช้ได้"""
    if not isinstance(result, list):
        return []
    out = []
    for item in result:
        if isinstance(item, dict) and isinstance(item.get("name"), str) and item["name"].strip():
            out.append({"name": clean_name(item["name"]), **{k: item.get(k) for k in keys}})
    return out


def _ask_json(prompt):
    try:
        return llm.chat_json(prompt)
    except (json.JSONDecodeError, ValueError):
        return None


def _llm_candidates(company, n, country, industry):
    prompt = LLM_PROMPT.format(n=n, company=company, country=country, industry=industry or "unknown")
    return _named_list(_ask_json(prompt), "reason")


def _news_candidates(company, headlines, industry):
    if not headlines:
        return []
    lines = "\n".join(f"{i}: {h['title']}" for i, h in enumerate(headlines))
    prompt = EXTRACT_PROMPT.format(company=company, lines=lines,
                                   industry_part=f" (industry: {industry})" if industry else "")
    out = []
    for item in _named_list(_ask_json(prompt), "headline_ids"):
        ids = item["headline_ids"] if isinstance(item["headline_ids"], list) else []
        evidence = [headlines[i] for i in ids if isinstance(i, int) and 0 <= i < len(headlines)]
        if evidence:  # ชื่อที่ไม่มีหัวข้อข่าวรองรับ ถือว่า LLM แต่งเอง ไม่นับ
            out.append({"name": item["name"], "evidence": evidence})
    return out


def _merge(company, pool):
    """รวมชื่อซ้ำ/ชื่อย่อด้วย LLM ถ้าตอบไม่ผ่านใช้ผลรวมแบบ rule (norm) ที่มีอยู่แล้ว"""
    if len(pool) < 2:
        return pool
    names = [c["name"] for c in pool.values()]
    groups = _named_list(_ask_json(MERGE_PROMPT.format(company=company, names="\n".join(names))), "members")
    by_name = {c["name"]: key for key, c in pool.items()}
    merged, used = {}, set()
    for g in groups:
        members = [m for m in (g["members"] or []) if isinstance(m, str) and m in by_name and m not in used]
        if not members or _is_self(g["name"], company):
            used.update(members)
            continue
        target = {"name": g["name"], "sources": set(), "reason": "", "evidence": []}
        for m in members:
            src = pool[by_name[m]]
            target["sources"] |= src["sources"]
            target["reason"] = target["reason"] or src["reason"]
            target["evidence"] += src["evidence"]
            used.add(m)
        merged[norm(g["name"])] = target
    if not merged:
        return pool
    # ชื่อที่ LLM ลืมใส่กลุ่ม ให้คงไว้ตามเดิม
    for key, c in pool.items():
        if c["name"] not in used:
            merged.setdefault(key, c)
    return merged


def _dedupe_links(items):
    seen, out = set(), []
    for it in items:
        if it["url"] not in seen:
            seen.add(it["url"])
            out.append({"title": it["title"], "url": it["url"]})
    return out


def discover(company, top_x=5, country="ประเทศไทย", industry=None, on_progress=None):
    """คืน {"found": bool, "message": str, "candidates": [...]} เรียงตามคะแนน ไม่เกิน top_x ราย"""
    say = on_progress or (lambda m: None)

    say("ค้นข่าวของบริษัทเรา")
    own_news = fetch_news(company, limit=20)
    if not own_news:
        return {"found": False, "candidates": [],
                "message": f"ไม่พบข่าวของ “{company}” เลย จึงหาคู่แข่งและวิเคราะห์ต่อไม่ได้ "
                           "ลองตรวจตัวสะกดหรือใช้ชื่อที่สื่อใช้บ่อย"}

    say("ถาม LLM ว่าใครเป็นคู่แข่ง")
    from_llm = _llm_candidates(company, top_x * 2, country, industry)

    say("ค้นข่าวที่พูดถึงคู่แข่ง")
    queries = [f"{company} คู่แข่ง", f"{company} competitors"] + ([f"{industry} ส่วนแบ่งตลาด"] if industry else [])
    headlines = _dedupe_links(own_news + [h for q in queries for h in fetch_news(q, limit=20)])
    say("ให้ LLM ดึงชื่อบริษัทจากหัวข้อข่าว")
    from_news = _news_candidates(company, headlines, industry)

    pool = {}
    for source, items in (("LLM", from_llm), ("ข่าว", from_news)):
        for it in items:
            if _is_self(it["name"], company):
                continue
            c = pool.setdefault(norm(it["name"]), {"name": it["name"], "sources": set(), "reason": "", "evidence": []})
            c["sources"].add(source)
            c["reason"] = c["reason"] or (it.get("reason") or "")
            c["evidence"] += it.get("evidence", [])
    if not pool:
        return {"found": False, "candidates": [],
                "message": f"ไม่พบคู่แข่งของ “{company}” ทั้งจาก LLM และจากข่าว ลองใส่อุตสาหกรรมเพิ่ม หรือพิมพ์รายชื่อเอง"}

    say("รวมชื่อซ้ำ")
    pool = _merge(company, pool)

    # ตรวจหลักฐานเฉพาะกลุ่มที่น่าจะติดอันดับ เพื่อไม่ยิง RSS มากเกินไป
    shortlist = sorted(pool.values(), key=lambda c: (-len(c["sources"]), -len(c["evidence"])))[:top_x * 2]
    for i, c in enumerate(shortlist, 1):
        say(f"ตรวจหลักฐาน {c['name']} ({i}/{len(shortlist)})")
        co = fetch_news(f'"{company}" "{c["name"]}"', limit=20)
        c["co_mentions"] = len(co)
        exists = bool(co) or bool(c["evidence"]) or bool(fetch_news(c["name"], limit=5))
        c["no_evidence"] = not exists
        c["evidence"] = _dedupe_links(co + c["evidence"])[:3]
        # ทั้งสองทาง 3, LLM อย่างเดียว 2 (มีเหตุผลประกอบ), ข่าวอย่างเดียว 1 + ข่าวที่พูดถึงคู่กันสูงสุด 1 คะแนน
        base = 3 if len(c["sources"]) == 2 else (2 if "LLM" in c["sources"] else 1)
        c["score"] = -1 if c["no_evidence"] else base + min(c["co_mentions"], 10) / 10
        c["sources"] = sorted(c["sources"])

    ranked = sorted(shortlist, key=lambda c: -c["score"])[:top_x]
    return {"found": True, "candidates": ranked,
            "message": f"พบ {len(ranked)} รายจาก {len(pool)} ชื่อที่รวบรวมได้"}
