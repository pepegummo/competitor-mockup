"""ถามข้อมูลที่ระบบเก็บไว้: ตอบจากข่าว/ประกาศ/รีวิว/งบที่ดึงมาแล้วเท่านั้น พร้อมเลข [n] ที่เป็นลิงก์ไปต้นทาง
ต่างจากถาม LLM ตรง ๆ: ไม่ใช้ความรู้ของโมเดล ไม่มีข้อมูลก็ตอบว่าไม่มี และรู้ว่าแต่ละข้อมาจากไหน
1) LLM แปลงคำถามเป็นตัวกรอง (บริษัท หมวด คำค้น ช่วงเวลา) → 2) pandas คัดรายการ → 3) LLM ตอบจากรายการที่คัดได้
ถ้าคัดได้ 0 รายการและไม่มีตัวเลขที่เกี่ยว จะตอบว่าไม่พบข้อมูลโดยไม่เรียก LLM ขั้นที่ 3"""
import json
from datetime import timedelta

import pandas as pd

from core import analyze, db, llm
from core.process import CATEGORIES

MAX_ROWS = 30
SOURCES = {"news": "ข่าว", "rss": "ข่าว", "website": "เว็บไซต์บริษัท", "set": "ประกาศ SET", "review": "รีวิวแอป"}

PARSE_PROMPT = """Turn this question about competitors into search filters.
Companies in the system (answer with the main name before the brackets): {companies}
Categories: product_price, promotion, news_pr, review, financial, hr, other
Question: {question}
Return ONLY JSON: {{"companies": [names from the list above, or [] for all],
"categories": [categories that fit, or [] for any], "keywords": [Thai/English words that must appear
in matching items, short (1–3 words each), or [] if the question is general],
"days": number of recent days the question asks about or null, "needs_numbers": true if the question is about
revenue, profit, ratios, ranking in the industry or stock price, else false}}"""

ANSWER_PROMPT = """You answer questions for a competitor-intelligence app. Use ONLY the data below.
Never use outside knowledge, even if you know the answer. Answer in Thai, concise (at most ~200 words),
bullets are fine. Put the ref number in square brackets right after every fact, e.g. "AP เปิดโครงการใหม่ [3]".
If the data does not answer the question, say "ไม่พบข้อมูลในระบบ" and briefly say what related data exists.
Mention dates when they matter. Do not write a reference list yourself, and never cite section names
such as [Financials] or [Sector ranks]; cite only ref numbers.
In Sector ranks, rank 1 is the best in the sector: only say "highest"/"best" when rank is 1,
otherwise state the rank, e.g. "อันดับ 4 จาก 34 บริษัทในหมวด".

Question: {question}

[Items: ข่าว/ประกาศ/รีวิวที่ระบบเก็บไว้และตรงกับคำถาม เรียงจากเกี่ยวข้องมากไปน้อย]
{items}{numbers}"""


def parse(question, companies):
    """คำถาม → {"companies", "categories", "keywords", "days", "needs_numbers"} (1 LLM call)"""
    aliases = {r["name"]: r["aliases"][:3] for r in db.get_companies(companies)}  # บาร์บีคิวพลาซ่า → ฟู้ดแพชชั่น
    listing = "; ".join(f"{c} (also called: {', '.join(aliases[c])})" if aliases.get(c) else c for c in companies)
    try:
        q = llm.chat_json(PARSE_PROMPT.format(companies=listing, question=question))
    except (json.JSONDecodeError, ValueError):
        q = {}
    q = q if isinstance(q, dict) else {}
    keep = {c.casefold(): c for c in companies}
    return {
        "companies": [keep[c.casefold()] for c in q.get("companies") or [] if isinstance(c, str) and c.casefold() in keep],
        "categories": [c for c in q.get("categories") or [] if c in CATEGORIES],
        "keywords": [k.strip() for k in q.get("keywords") or [] if isinstance(k, str) and k.strip()][:6],
        "days": q.get("days") if isinstance(q.get("days"), int) and q.get("days") > 0 else None,
        "needs_numbers": bool(q.get("needs_numbers")),
    }


def retrieve(df, f):
    """คัดรายการตามตัวกรอง เรียงตามจำนวนคำค้นที่เจอ แล้วตามความใหม่ (ไม่เกิน 30 รายการ)"""
    if df.empty:
        return df
    v = df[df["category"] != "irrelevant"] if "category" in df else df
    if f["companies"]:
        v = v[v["company"].isin(f["companies"])]
    if f["days"]:
        v = v[v["published_dt"] >= pd.Timestamp.now(tz="UTC") - timedelta(days=f["days"])]
    if f["keywords"] and not v.empty:
        # มีคำค้น: ต้องเจออย่างน้อย 1 คำ หมวดที่ตรงได้คะแนนเพิ่ม (ไม่ตัดทิ้ง เพราะหมวดที่ LLM จัดอาจไม่ตรงคำถาม)
        text = (v["title"].fillna("") + " " + v["summary"].fillna("") + " " + v["content"].fillna("")).str.lower()
        hits = sum(text.str.contains(k.lower(), regex=False).astype(int) for k in f["keywords"])
        v = v.assign(_score=hits * 2 + v["category"].isin(f["categories"]).astype(int))[hits > 0]
    elif f["categories"]:
        v = v[v["category"].isin(f["categories"])].assign(_score=0)
    else:
        v = v.assign(_score=0)
    return v.sort_values(["_score", "published_dt"], ascending=False).head(MAX_ROWS)


def answer(question, df, companies, fin=None, sector=None, price=None):
    """คืน {"answer": markdown (เลข [n] เป็นลิงก์), "filters", "used": จำนวนรายการ, "llm_calls"}"""
    calls = llm.call_count
    f = parse(question, companies)
    rows = retrieve(df, f)
    refs = []

    def add_ref(title, url):
        refs.append((title or url, url))
        return len(refs)

    items = pd.DataFrame({
        "ref": [add_ref(t, u) if isinstance(u, str) and u else "" for t, u in zip(rows["title"], rows["url"])],
        "company": rows["company"], "date": rows["published_dt"].dt.strftime("%Y-%m-%d"),
        "source": rows["source_type"].map(SOURCES), "category": rows["category"], "sentiment": rows["sentiment"],
        "title": rows["title"].str.slice(0, 160), "summary": rows["summary"],
    }) if not rows.empty else pd.DataFrame()

    numbers = ""
    scope = f["companies"] or companies
    if f["needs_numbers"]:
        if fin is not None and not fin.empty:
            t = fin[fin.index.isin(scope)].dropna(axis=1, how="all")
            if not t.empty:
                symbols = t["symbol"] if "symbol" in t else [None] * len(t)
                t = t.assign(ref=[add_ref(f"งบการเงิน {n} จาก SET", analyze.SET_FACTSHEET.format(s))
                                  if isinstance(s, str) and s else "" for n, s in zip(t.index, symbols)])
                numbers += "\n\n[Financials: งบล่าสุดจาก SET ตัวเงินล้านบาท _pct = %]\n" + t.to_markdown()
        if sector is not None and not sector.empty:
            s = sector[sector["company"].isin(scope)]
            if not s.empty:
                sref = {sym: add_ref(f"ตัวเลข {sym} เทียบหมวด{sec} จาก SET", analyze.SET_FACTSHEET.format(sym))
                        for sym, sec in s[["symbol", "sector"]].drop_duplicates().itertuples(index=False)}
                s = s.assign(ref=s["symbol"].map(sref))[["ref", "company", "sector", "metric", "value", "rank",
                                                          "n", "median"]]
                numbers += ("\n\n[Sector ranks: อันดับในหมวดธุรกิจ SET rank 1 = ดีที่สุด n = จำนวนบริษัทในหมวด]\n"
                            + s.to_markdown(index=False))
        if price is not None and not price.empty:
            p = price[price["company"].isin(scope)].head(10)
            if not p.empty:
                p_tab = pd.DataFrame({
                    "ref": [add_ref(t[0], u[0]) if u and u[0] else "" for t, u in zip(p["titles"], p["urls"])],
                    "company": p["company"], "date": p["date"], "r1_pct": p["r1_pct"], "r3_pct": p["r3_pct"],
                    "z": p["z"], "abnormal": p["big"], "headline": [t[0][:120] for t in p["titles"]]})
                numbers += ("\n\n[Stock moves after news: r1/r3 = % เปลี่ยน 1/3 วันทำการ z = เท่าของความผันผวนปกติ]\n"
                            + p_tab.to_markdown(index=False))

    if items.empty and not numbers:
        return {"answer": "ไม่พบข้อมูลในระบบที่ตรงกับคำถามนี้ ลองถามให้กว้างขึ้น หรือกดวิเคราะห์ใหม่เพื่อดึงข้อมูลล่าสุด",
                "filters": f, "used": 0, "llm_calls": llm.call_count - calls}
    text = llm.chat(ANSWER_PROMPT.format(question=question,
                                         items=items.to_markdown(index=False) if not items.empty else "(ไม่มี)",
                                         numbers=numbers)).strip()
    text = analyze.link_refs(analyze.CJK.sub("", text), refs)
    return {"answer": text, "filters": f, "used": len(items), "llm_calls": llm.call_count - calls}
