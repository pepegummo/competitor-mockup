import pandas as pd

from core import db, llm

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
gap_pts = us_pct − competitor_avg_pct (หน่วยเป็นจุด %; แถว type=review: avg_stars เป็นดาว 1–5)]
{gap}"""


REVIEW_SECTION = """

[Table R: รีวิวแอปของลูกค้าจาก App Store / Google Play — reviews = จำนวนรีวิว,
avg_stars = คะแนนเฉลี่ย 1–5 ดาว, positive_pct/negative_pct = % ของรีวิว]
{r}"""


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


def gap_table(df, table_b, self_name, reviews=None):
    """ค่าของเรา − ค่าเฉลี่ยคู่แข่ง: category (% ของข่าวแต่ละบริษัท), sentiment (%), รีวิว (ดาว, % รีวิวลบ)"""
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
    return pd.DataFrame(rows)


def build_tables(company_ids):
    """ตัวเลขทั้งหมดคิดด้วย pandas ไม่ให้ LLM นับเอง"""
    """คืน (df ทุกแหล่งรวมรีวิว, ตาราง A, B, C ที่คิดจากข่าว + เว็บไซต์เท่านั้น)"""
    df = db.facts_df(company_ids)
    if df.empty:
        return df, pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
    df["published_dt"] = pd.to_datetime(df["published_at"], errors="coerce", utc=True, format="mixed")
    news = news_only(df)
    if news.empty:
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


def write_report(table_a, table_b, table_c, self_name=None, gap=None, mode=None, reviews=None):
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
    if reviews is not None and not reviews.empty:
        prompt += REVIEW_SECTION.format(r=reviews.to_markdown())
    report = llm.chat(prompt).strip()
    db.save_report(mode, report)
    return report
