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
gap_pts = us_pct − competitor_avg_pct (หน่วยเป็นจุด %)]
{gap}"""


def gap_table(df, table_b, self_name):
    """ค่าของเรา − ค่าเฉลี่ยคู่แข่ง ทั้ง category (เป็น % ของข่าวแต่ละบริษัท) และ sentiment (%)"""
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
    return pd.DataFrame(rows)


def build_tables(company_ids):
    """ตัวเลขทั้งหมดคิดด้วย pandas ไม่ให้ LLM นับเอง"""
    df = db.facts_df(company_ids)
    if df.empty:
        return df, pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

    table_a = pd.crosstab(df["company"], df["category"], margins=True, margins_name="รวม")

    table_b = (pd.crosstab(df["company"], df["sentiment"], normalize="index") * 100).round(1)
    table_b = table_b.reindex(columns=["positive", "neutral", "negative"], fill_value=0)

    df["published_dt"] = pd.to_datetime(df["published_at"], errors="coerce", utc=True)
    table_c = (df.sort_values("published_dt", ascending=False)
                 .groupby("company").head(5)
                 .sort_values(["company", "published_dt"], ascending=[True, False])
                 [["company", "published_dt", "category", "sentiment", "summary"]]
                 .rename(columns={"published_dt": "date"}))
    table_c["date"] = table_c["date"].dt.strftime("%Y-%m-%d")
    return df, table_a, table_b, table_c


def write_report(table_a, table_b, table_c, self_name=None, gap=None, mode=None):
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
    report = llm.chat(prompt).strip()
    db.save_report(mode, report)
    return report
