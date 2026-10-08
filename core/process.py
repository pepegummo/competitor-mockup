import json
from itertools import groupby

from core import db, llm

CATEGORIES = {"product_price", "promotion", "news_pr", "review", "financial", "hr", "other"}
SENTIMENTS = {"positive", "neutral", "negative"}
BATCH_SIZE = 10

PROMPT = """You are a business analyst. Classify each news headline about a company.

Categories: product_price, promotion, news_pr, review, financial, hr, other
Sentiment (toward the company): positive, neutral, negative

Return ONLY a JSON array, one object per headline:
[{{"id": <id>, "category": "...", "sentiment": "...", "summary": "<สรุปภาษาไทย 1 ประโยค>"}}]

Company: {company}
Headlines:
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


def _classify_batch(company, docs):
    sent_ids = {d["id"] for d in docs}
    lines = "\n".join(f"{d['id']}: {d['title']}" for d in docs)
    prompt = PROMPT.format(company=company, lines=lines)
    for _ in range(2):  # ลอง 1 ครั้ง + ลองใหม่ 1 ครั้ง
        try:
            checked = _validate(llm.chat_json(prompt), sent_ids)
        except (json.JSONDecodeError, ValueError):
            checked = None
        if checked:
            return checked
    return None


def classify_pending(company_ids, on_progress=None):
    """classify เฉพาะ documents ที่ยังไม่มี fact. คืน (จำนวนที่บันทึก, จำนวน batch ที่ข้าม)"""
    docs = db.unprocessed_documents(company_ids)
    saved, skipped = 0, 0
    batches = []
    for (company_id, company), group in groupby(docs, key=lambda d: (d["company_id"], d["company"])):
        group = list(group)
        for i in range(0, len(group), BATCH_SIZE):
            batches.append((company_id, company, group[i:i + BATCH_SIZE]))

    for n, (company_id, company, batch) in enumerate(batches, 1):
        if on_progress:
            on_progress(f"Classify {company} ({n}/{len(batches)})")
        result = _classify_batch(company, batch)
        if result is None:
            skipped += 1
            continue
        for doc_id, item in result.items():
            db.insert_fact(doc_id, company_id, item["category"], item["sentiment"],
                           str(item.get("summary", "")).strip())
            saved += 1
    return saved, skipped
