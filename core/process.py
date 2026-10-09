import json
from concurrent.futures import ThreadPoolExecutor
from itertools import groupby

from core import db, llm

CATEGORIES = {"product_price", "promotion", "news_pr", "review", "financial", "hr", "other"}
IRRELEVANT = "irrelevant"  # เก็บไว้เป็น fact เพื่อไม่ส่งให้ LLM ซ้ำ แต่ไม่นำไปวิเคราะห์ (db.facts_df ตัดออก)
CHECKED_SOURCES = {"news", "rss"}  # แหล่งที่ค้นด้วยชื่อ จึงอาจได้เรื่องอื่นที่ชื่อซ้ำ
SENTIMENTS = {"positive", "neutral", "negative"}
LLM_WORKERS = 4          # ชุดที่ส่ง LLM พร้อมกัน
BATCH_SIZE = 10          # หัวข้ออย่างเดียว
BATCH_SIZE_CONTENT = 5   # มีเนื้อหา/รีวิว prompt ยาวขึ้น จึงส่งทีละน้อยลง
CONTENT_CHARS = 600
SOURCE_TAG = {"news": "news", "rss": "news", "website": "company website", "review": "app review"}

PROMPT = """You are a business analyst. Classify each item about a company.
Items are news headlines, company website pages, or customer app reviews (marked [app review]).

Categories: product_price, promotion, news_pr, review, financial, hr, other
Use category "review" for every [app review] item.
Sentiment (toward the company): positive, neutral, negative
For app reviews, sentiment is how the reviewer feels about the company or its app.

"relevant" (news items only): true if the item is really about this company — its business, products,
people, results or stock. false if the name means something else (a street, a TV host, a news agency,
another company with the same abbreviation) or the company is only one name in a list of many stocks
with no news about it. Company website pages and app reviews are always relevant.

Return ONLY a JSON array, one object per item:
[{{"id": <id>, "relevant": true, "category": "...", "sentiment": "...", "summary": "<สรุปภาษาไทย 1 ประโยค>"}}]
{examples}
Company: {company}
Items:
{lines}"""


def _validate(result, sent_ids):
    """คืน dict id → item ถ้าผ่าน, ไม่ผ่านคืน None"""
    if not isinstance(result, list):
        return None
    out = {}
    for item in result:
        if not isinstance(item, dict):
            return None
        try:
            doc_id = int(item.get("id"))
        except (TypeError, ValueError):
            return None
        if (doc_id not in sent_ids
                or item.get("category") not in CATEGORIES
                or item.get("sentiment") not in SENTIMENTS):
            return None
        out[doc_id] = item
    if set(out) != sent_ids:
        return None
    return out


def _line(d):
    tag = SOURCE_TAG.get(d["source_type"] or "news", "news")
    line = f"{d['id']} [{tag}]: {d['title']}"
    content = " ".join((d["content"] or "").split())
    if content and content != d["title"]:
        line += f"\n    text: {content[:CONTENT_CHARS]}"
    return line


def describe(row):
    """บอก LLM ว่าบริษัทนี้คือใคร เพื่อแยกจากสิ่งอื่นที่ชื่อเหมือนกัน"""
    parts = [row["name"]]
    if row.get("aliases"):
        parts.append("also called " + ", ".join(row["aliases"]))
    if row.get("set_symbol"):
        parts.append(f"SET symbol {row['set_symbol']}")
    if row.get("business"):
        parts.append(f"business: {row['business']}")
    return " · ".join(parts)


EXAMPLES = """
Items the user already checked by hand. Follow the same judgement for similar items:
{rows}
"""


def examples_text(company):
    """ข่าวที่ผู้ใช้ตรวจแล้ว (เน้นที่ระบบเคยตัดสินผิด) ของบริษัทนี้ก่อน → ตัวอย่างให้ LLM
    ระบบจึงแม่นขึ้นตามที่องค์กรตรวจ"""
    rows = []
    for e in db.label_examples(company):
        verdict = ("relevant false" if not e["relevant"] else "relevant true"
                   + (f", category {e['category']}" if e["category"] else "")
                   + (f", sentiment {e['sentiment']}" if e["sentiment"] else ""))
        rows.append(f'- {e["company"]}: "{e["title"][:120]}" → {verdict}')
    return EXAMPLES.format(rows="\n".join(rows)) if rows else ""


def _classify_batch(company, docs, examples=""):
    sent_ids = {d["id"] for d in docs}
    lines = "\n".join(_line(d) for d in docs)
    prompt = PROMPT.format(company=company, lines=lines, examples=examples)
    for _ in range(2):  # ลอง 1 ครั้ง + ลองใหม่ 1 ครั้ง
        try:
            checked = _validate(llm.chat_json(prompt), sent_ids)
        except (json.JSONDecodeError, ValueError):
            checked = None
        if checked:
            return checked
    return None


def classify_pending(company_ids, on_progress=None):
    """classify เฉพาะ documents ที่ยังไม่มี fact
    คืน (จำนวนที่บันทึก, จำนวน batch ที่ข้าม, จำนวนข่าวที่ไม่ใช่เรื่องของบริษัทนั้น)"""
    docs = db.unprocessed_documents(company_ids)
    saved, skipped, dropped = 0, 0, 0
    batches = []
    for (company_id, company), group in groupby(docs, key=lambda d: (d["company_id"], d["company"])):
        group = list(group)
        short = [d for d in group if not d["content"]]
        long_ = [d for d in group if d["content"]]
        for docs_, size in ((short, BATCH_SIZE), (long_, BATCH_SIZE_CONTENT)):
            for i in range(0, len(docs_), size):
                batches.append((company_id, company, docs_[i:i + size]))
    profiles = {r["name"]: describe(r) for r in db.get_companies(list({d["company"] for d in docs}))}
    examples = {name: examples_text(name) for name in profiles} if batches else {}

    # ส่ง LLM หลายชุดพร้อมกัน (ช่วงที่ใช้เวลามากที่สุดของการวิเคราะห์) แล้วบันทึกผลตามลำดับในเธรดหลัก
    pool = ThreadPoolExecutor(LLM_WORKERS)
    futures = [pool.submit(_classify_batch, profiles.get(company, company), batch, examples.get(company, ""))
               for company_id, company, batch in batches]
    pool.shutdown(wait=False)
    for n, ((company_id, company, batch), future) in enumerate(zip(batches, futures), 1):
        if on_progress:
            on_progress(f"Classify {company} ({n}/{len(batches)})")
        result = future.result()
        if result is None:
            skipped += 1
            continue
        types = {d["id"]: d["source_type"] or "news" for d in batch}
        for doc_id, item in result.items():
            category = item["category"]
            if item.get("relevant") is False and types[doc_id] in CHECKED_SOURCES:
                category = IRRELEVANT
                dropped += 1
            else:
                saved += 1
            db.insert_fact(doc_id, company_id, category, item["sentiment"], str(item.get("summary", "")).strip())
    return saved, skipped, dropped
