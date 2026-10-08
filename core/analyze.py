import re

import pandas as pd

from core import db, llm

CJK = re.compile(r"[㐀-鿿豈-﫿]+")

REPORT_PROMPT = """You are a market analyst. Using ONLY the data below, write a comparison
of these companies in Thai (markdown, under 300 words).
Cover: what each company is focusing on, who gets the most positive/negative
coverage, and notable recent moves. Do not invent facts or numbers.
Write in Thai only (English company/product names are fine); never use Chinese characters.

[Table A: จำนวนข่าวต่อบริษัท × category]
{a}

[Table B: สัดส่วน sentiment ต่อบริษัท (%)]
{b}

[Table C: ข่าวล่าสุด 5 รายการต่อบริษัท]
{c}"""


REPORT_PROMPT_SELF = """You are a strategy advisor for {self_company}. Using ONLY the data below,
write in Thai (markdown, under 400 words):
1. Where {self_company} is ahead of competitors
2. Where it is behind
3. Threats: recent competitor moves that could hurt us
4. Opportunities: gaps no competitor is covering
5. 3 recommended actions, each tied to a specific data point
Do not invent facts or numbers.
Write in Thai only (English company/product names are fine); never use Chinese characters.

[Table A: จำนวนข่าวต่อบริษัท × category]
{a}

[Table B: สัดส่วน sentiment ต่อบริษัท (%)]
{b}

[Table C: ข่าวล่าสุด 5 รายการต่อบริษัท]
{c}

[Gap table: {self_company} เทียบค่าเฉลี่ยคู่แข่ง — category คิดเป็น % ของข่าวทั้งหมดของแต่ละบริษัท,
gap_pts = us_pct − competitor_avg_pct (หน่วยเป็นจุด %; แถว type=review: avg_stars เป็นดาว 1–5;
แถว type=finance มาจากงบการเงิน หน่วยเป็น %)]
{gap}"""


REVIEW_SECTION = """

[Table R: รีวิวแอปของลูกค้าจาก App Store / Google Play — reviews = จำนวนรีวิว,
avg_stars = คะแนนเฉลี่ย 1–5 ดาว, positive_pct/negative_pct = % ของรีวิว]
{r}"""


FINANCE_SECTION = """

[Table F: งบการเงินล่าสุดที่บริษัทยื่นต่อตลาดหลักทรัพย์ฯ (งบรวม) — ตัวเงินหน่วยล้านบาท,
period = ช่วงสะสมของงบ (เช่น 6M/2026 = ครึ่งปีแรก), *_yoy_pct = เติบโตเทียบช่วงเดียวกันปีก่อน (%),
margin = % ของรายได้รวม, roe_pct/de_ratio มาจากงบทั้งปีล่าสุด (ปี fy).
ถ้า period ต่างกัน ห้ามเทียบตัวเลขเงินตรง ๆ ให้เทียบ % แทน
บริษัทที่ไม่อยู่ในตารางนี้ไม่ได้จดทะเบียนในตลาดหลักทรัพย์ฯ จึงไม่มีงบ ห้ามเดาตัวเลขให้]
{f}"""


def news_only(df):
    """ข่าว + เว็บไซต์บริษัท (ไม่รวมรีวิว) ใช้กับตาราง A/B/C เพื่อไม่ให้รีวิวจำนวนมากกลบหมวดข่าว"""
    return df[df["source_type"] != "review"] if not df.empty else df


def review_table(df):
    """Table R: ต่อบริษัท จำนวนรีวิว คะแนนเฉลี่ย (รวมและแยกสโตร์) และ % รีวิวบวก/ลบ"""
    r = df[df["source_type"] == "review"] if not df.empty else df
    if r.empty:
        return pd.DataFrame()
    g = r.groupby("company")
    table = pd.DataFrame({"reviews": g.size(), "avg_stars": g["rating"].mean().round(2)})
    for store, col in (("App Store", "avg_stars_app_store"), ("Google Play", "avg_stars_google_play")):
        table[col] = r[r["source_name"] == store].groupby("company")["rating"].mean().round(2)
    sent = (pd.crosstab(r["company"], r["sentiment"], normalize="index") * 100).round(1)
    for s in ("positive", "negative"):
        table[f"{s}_pct"] = sent[s] if s in sent else 0.0
    return table.fillna({"positive_pct": 0.0, "negative_pct": 0.0})


def _pct(new, old):
    """% เติบโต (ฐานติดลบหรือเป็นศูนย์ไม่มีความหมาย คืน None)"""
    if new is None or not old or old <= 0:
        return None
    return round((new - old) / old * 100, 1)


def financial_table(fins):
    """Table F: ต่อบริษัทที่มีงบ ค่าทั้งหมดคิดจากตัวเลขในงบที่ SET ให้มา"""
    rows = {}
    for name, f in fins.items():
        cur, prev = f["latest"], f.get("previous") or {}
        rev, np_ = cur.get("revenue"), cur.get("net_profit")
        full_years = [h for h in f.get("history", []) if h["period"] == "ทั้งปี"]
        fy = full_years[-1] if full_years else {}
        rows[name] = {
            "period": cur["period"],
            "revenue_mb": round(rev) if rev is not None else None,
            "revenue_yoy_pct": _pct(rev, prev.get("revenue")),
            "net_profit_mb": round(np_) if np_ is not None else None,
            "net_profit_yoy_pct": _pct(np_, prev.get("net_profit")),
            "net_margin_pct": round(np_ / rev * 100, 1) if rev and np_ is not None else None,
            "ebitda_margin_pct": round(cur["ebitda"] / rev * 100, 1) if rev and cur.get("ebitda") is not None else None,
            "fy": fy.get("year"),
            "roe_pct": round(fy["roe"], 1) if fy.get("roe") is not None else None,
            "de_ratio": round(fy["de_ratio"], 2) if fy.get("de_ratio") is not None else None,
            "market_cap_mb": f["market"].get("market_cap"),
            "pe": f["market"].get("pe"),
            "dividend_yield_pct": f["market"].get("dividend_yield"),
        }
    return pd.DataFrame.from_dict(rows, orient="index").rename_axis("company")


FINANCE_GAP_ITEMS = ("revenue_yoy_pct", "net_margin_pct", "roe_pct")


def gap_table(df, table_b, self_name, reviews=None, fin=None):
    """ค่าของเรา − ค่าเฉลี่ยคู่แข่ง: category (% ของข่าวแต่ละบริษัท), sentiment (%), รีวิว (ดาว, % รีวิวลบ),
    การเงิน (% เติบโต, อัตรากำไร, ROE)"""
    df = news_only(df)
    if df.empty or self_name not in set(df["company"]):
        return pd.DataFrame()
    share = pd.crosstab(df["company"], df["category"], normalize="index") * 100
    competitors = [c for c in share.index if c != self_name]
    if not competitors:
        return pd.DataFrame()
    rows = []
    for kind, table in (("category", share), ("sentiment", table_b)):
        for item in table.columns:
            us = float(table.loc[self_name, item])
            avg = float(table.loc[competitors, item].mean())
            rows.append({"type": kind, "item": item, "us_pct": round(us, 1),
                         "competitor_avg_pct": round(avg, 1), "gap_pts": round(us - avg, 1)})
    # รีวิว: ใช้ได้เมื่อทั้งเราและคู่แข่งอย่างน้อย 1 รายมีรีวิว (ค่า avg_stars เป็นดาว ไม่ใช่ %)
    if reviews is not None and not reviews.empty and self_name in reviews.index:
        rc = [c for c in competitors if c in reviews.index]
        for item in ("avg_stars", "negative_pct"):
            if rc and pd.notna(reviews.loc[self_name, item]):
                us, avg = float(reviews.loc[self_name, item]), float(reviews.loc[rc, item].mean())
                rows.append({"type": "review", "item": item, "us_pct": round(us, 2),
                             "competitor_avg_pct": round(avg, 2), "gap_pts": round(us - avg, 2)})
    # การเงิน: ใช้เฉพาะคู่แข่งที่มีตัวเลขนั้น (บริษัทนอกตลาดไม่มีงบ)
    if fin is not None and not fin.empty and self_name in fin.index:
        for item in FINANCE_GAP_ITEMS:
            us = fin.loc[self_name, item]
            others = fin.loc[[c for c in competitors if c in fin.index], item].dropna()
            if pd.notna(us) and not others.empty:
                rows.append({"type": "finance", "item": item, "us_pct": round(float(us), 1),
                             "competitor_avg_pct": round(float(others.mean()), 1),
                             "gap_pts": round(float(us) - float(others.mean()), 1)})
    return pd.DataFrame(rows)


def load_df(company_ids):
    """ทุกรายการที่จัดหมวดแล้วของบริษัทเหล่านี้ (ข่าว เว็บไซต์ ข่าวแจ้งตลาด รีวิว)"""
    df = db.facts_df(company_ids)
    if not df.empty:
        df["published_dt"] = pd.to_datetime(df["published_at"], errors="coerce", utc=True, format="mixed")
    return df


def apply_focus(df, focus):
    """เหลือเฉพาะเรื่องที่สนใจ: ข่าวต้องอยู่ในหมวดที่เลือก (ถ้าเลือก) และ ทุกรายการต้องมีคำค้น (ถ้าใส่)
    รีวิวไม่ถูกกรองด้วยหมวด เพราะรีวิวทุกอันอยู่หมวด review"""
    focus = focus or {}
    cats, words = focus.get("categories") or [], [w.lower() for w in focus.get("keywords") or []]
    if df.empty or not (cats or words):
        return df
    keep = pd.Series(True, index=df.index)
    if cats:
        keep &= (df["source_type"] == "review") | df["category"].isin(cats)
    if words:
        text = (df["title"].fillna("") + " " + df["summary"].fillna("") + " " + df["content"].fillna("")).str.lower()
        keep &= text.apply(lambda t: any(w in t for w in words))
    return df[keep]


def focus_label(focus, category_names=None):
    focus = focus or {}
    cats = [(category_names or {}).get(c, c) for c in focus.get("categories") or []]
    return " · ".join(list(focus.get("keywords") or []) + cats)


def build_tables(company_ids, focus=None):
    """ตัวเลขทั้งหมดคิดด้วย pandas ไม่ให้ LLM นับเอง"""
    return tables_from_df(apply_focus(load_df(company_ids), focus))


def tables_from_df(df):
    """คืน (df ทุกแหล่งรวมรีวิว, ตาราง A, B, C ที่คิดจากข่าว + เว็บไซต์เท่านั้น)"""
    news = news_only(df)
    if df.empty or news.empty:
        return df, pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

    table_a = pd.crosstab(news["company"], news["category"], margins=True, margins_name="รวม")

    table_b = (pd.crosstab(news["company"], news["sentiment"], normalize="index") * 100).round(1)
    table_b = table_b.reindex(columns=["positive", "neutral", "negative"], fill_value=0)

    table_c = (news.sort_values("published_dt", ascending=False)
                 .groupby("company").head(5)
                 .sort_values(["company", "published_dt"], ascending=[True, False])
                 [["company", "published_dt", "category", "sentiment", "summary"]]
                 .rename(columns={"published_dt": "date"}))
    table_c["date"] = table_c["date"].dt.strftime("%Y-%m-%d")
    return df, table_a, table_b, table_c


def write_report(table_a, table_b, table_c, self_name=None, gap=None, mode=None, reviews=None, fin=None,
                 scope=None):
    """scope = ข้อความบอกว่าข้อมูลถูกกรองเฉพาะเรื่อง/ช่วงไหน (ให้ LLM เขียนเน้นเรื่องนั้น)"""
    """ไม่มี self_name = รายงานกลาง ๆ (phase1), มี self_name = มุมมองบริษัทเรา (phase2/phase3)"""
    tables = dict(a=table_a.to_markdown(), b=table_b.to_markdown(),
                  c=table_c.to_markdown(index=False))
    if self_name:
        prompt = REPORT_PROMPT_SELF.format(self_company=self_name,
                                           gap=gap.to_markdown(index=False), **tables)
        mode = mode or "phase2"
    else:
        prompt = REPORT_PROMPT.format(**tables)
        mode = mode or "phase1"
    if scope:
        prompt += (f"\n\n[Scope: the tables above only include items about / filtered by: {scope}. "
                   "Focus the report on this scope and say so in the first sentence.]")
    if reviews is not None and not reviews.empty:
        prompt += REVIEW_SECTION.format(r=reviews.to_markdown())
    if fin is not None and not fin.empty:
        prompt += FINANCE_SECTION.format(f=fin.to_markdown())
    report = llm.chat(prompt).strip()
    if CJK.search(report):  # โมเดลบางครั้งหลุดคำภาษาจีนแม้สั่งไว้แล้ว ให้เขียนใหม่ 1 ครั้ง
        report = llm.chat(prompt + "\n\nIMPORTANT: Thai script only. Do not output any Chinese characters.").strip()
    report = CJK.sub("", report)
    db.save_report(mode, report)
    return report
