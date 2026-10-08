import json
from itertools import groupby

from core import db, llm

CATEGORIES = {"product_price", "promotion", "news_pr", "review", "financial", "hr", "other"}
SENTIMENTS = {"positive", "neutral", "negative"}
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

Return ONLY a JSON array, one object per item:
[{{"id": <id>, "category": "...", "sentiment": "...", "summary": "<สรุปภาษาไทย 1 ประโยค>"}}]

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


def _classify_batch(company, docs):
    sent_ids = {d["id"] for d in docs}
    lines = "\n".join(_line(d) for d in docs)
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
        short = [d for d in group if not d["content"]]
        long_ = [d for d in group if d["content"]]
        for docs_, size in ((short, BATCH_SIZE), (long_, BATCH_SIZE_CONTENT)):
            for i in range(0, len(docs_), size):
                batches.append((company_id, company, docs_[i:i + size]))

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
