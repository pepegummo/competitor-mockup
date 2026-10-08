import pandas as pd

from core import db, llm

REPORT_PROMPT = """You are a market analyst. Using ONLY the data below, write a comparison
of these companies in Thai (markdown, under 300 words).
Cover: what each company is focusing on, who gets the most positive/negative
coverage, and notable recent moves. Do not invent facts or numbers.

[Table A: จำนวนข่าวต่อบริษัท × category]
{a}

[Table B: สัดส่วน sentiment ต่อบริษัท (%)]
{b}

[Table C: ข่าวล่าสุด 5 รายการต่อบริษัท]
{c}"""


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


def write_report(table_a, table_b, table_c):
    prompt = REPORT_PROMPT.format(
        a=table_a.to_markdown(),
        b=table_b.to_markdown(),
        c=table_c.to_markdown(index=False),
    )
    report = llm.chat(prompt).strip()
    db.save_report("phase1", report)
    return report
