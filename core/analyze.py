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
sector = หมวดธุรกิจใน SET บริษัทต่างหมวดกันใช้แบบงบต่างกัน อย่าเทียบอัตรากำไรข้ามหมวดตรง ๆ
ธนาคาร: revenue = รายได้จากการดำเนินงาน (ดอกเบี้ยสุทธิ + ค่าธรรมเนียมสุทธิ + อื่น ๆ), nii = รายได้ดอกเบี้ยสุทธิ,
nim_approx_pct = nii ต่อปี ÷ สินทรัพย์รวม (ค่าประมาณของ NIM), cost_to_income_pct = ค่าใช้จ่ายดำเนินงาน ÷ revenue,
credit_cost_pct = ผลขาดทุนด้านเครดิตต่อปี ÷ สินเชื่อ, ldr_pct = สินเชื่อ ÷ เงินฝาก ไม่มีข้อมูล NPL
บริษัทที่ไม่อยู่ในตารางนี้ไม่ได้จดทะเบียนในตลาดหลักทรัพย์ฯ จึงไม่มีงบ ห้ามเดาตัวเลขให้]
{f}"""


INTERNAL_SECTION = """

[Table I: ข้อมูลภายในที่ผู้ใช้อัปโหลดเอง (ไม่ได้มาจากแหล่งสาธารณะ) — company × metric, หน่วยและช่วงเวลาอยู่ในตาราง U
ใช้ตัวเลขตามที่ให้มาเท่านั้น และบอกว่าเป็น "ข้อมูลภายใน" เมื่ออ้างถึง]
{i}

[Table U: หน่วยและช่วงเวลาของแต่ละ metric]
{u}"""


SECTOR_SECTION = """

[Table S: อันดับเมื่อเทียบกับทุกบริษัทจดทะเบียนในหมวดธุรกิจเดียวกันของ SET (ไม่ใช่แค่คู่แข่งที่เลือก)
rank 1 = ดีที่สุดในหมวด (de_ratio และ pe: ต่ำ = อันดับดี), n = จำนวนบริษัทในหมวดที่มีตัวเลขนี้,
median = ค่ามัธยฐานของหมวด, ตัวเลขจากงบทั้งปีล่าสุด หน่วยตาม metric (_pct = %, _mb = ล้านบาท)
ใช้ประโยคเช่น "อัตรากำไรสุทธิของ X อยู่อันดับ 4 จาก 34 บริษัทในหมวดพาณิชย์" ห้ามเทียบอันดับข้ามหมวด]
{s}"""


PRICE_SECTION = """

[Table P: ราคาหุ้นหลังข่าว — วันที่มีข่าว/ประกาศแล้วหุ้นขยับผิดปกติ (คิดจากราคาปิด SET ไม่ใช่การเดา)
r1_pct/r3_pct = % เปลี่ยนของราคาใน 1/3 วันทำการเทียบกับราคาปิดก่อนข่าว, z = กี่เท่าของความผันผวนปกติของหุ้นนั้น
headlines = ข่าวของวันนั้น ยังไม่ได้หักผลของตลาดรวม จึงใช้คำว่า "หุ้นขยับหลังข่าว" ไม่ใช่ "ข่าวทำให้หุ้นขยับ"]
{p}"""


CHANGES_SECTION = """

[Changes: สิ่งที่เปลี่ยนไปตั้งแต่รอบวิเคราะห์ก่อน (ระบบคิดจากข้อมูล ไม่ใช่การเดา) level high = สำคัญ]
{ch}
Start the report with a short section "สิ่งที่เปลี่ยนไปตั้งแต่รอบก่อน" (2–5 bullets, most important first)
before the rest of the report."""


CITE_RULE = """

Citations: rows in Table C, Table F, Table S, Table P and Changes have a "ref" number. Whenever you state a fact taken from one of
those rows, put its number in square brackets right after the sentence, e.g. "AIS เปิดตัวแพ็กเกจใหม่ [3]".
Use only ref numbers that appear above. Never cite table names such as [Table F] or [Gap table].
Do not write a reference list yourself."""


GROUP_SECTION = """

[Group structure: บริษัทในเครือที่ถูกเพิ่มแยกเป็นรายบริษัท (company → parent, relation)
บริษัทในเครืออาจอยู่คนละธุรกิจกับบริษัทแม่ ให้อธิบายเป็นส่วนหนึ่งของเครือนั้น ห้ามนับเป็นคู่แข่งของบริษัทแม่
หรือของบริษัทในเครือเดียวกัน]
{g}"""


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


def _ratio(num, den, annualize_months=None):
    """num ÷ den เป็น % (annualize_months: แปลงงบสะสม n เดือนเป็นต่อปีก่อนหาร)"""
    if num is None or not den:
        return None
    if annualize_months:
        num = num * 12 / annualize_months
    return round(num / den * 100, 2)


def bank_metrics(cur, prev):
    """ตัวชี้วัดเฉพาะธนาคาร (คืน {} ถ้างบไม่มีรายได้ดอกเบี้ยสุทธิ)"""
    if cur.get("nii") is None:
        return {}
    months = cur.get("months") or 12
    return {
        "nii_mb": round(cur["nii"]),
        "nii_yoy_pct": _pct(cur["nii"], prev.get("nii")),
        "fee_income_mb": round(cur["fee_income"]) if cur.get("fee_income") is not None else None,
        "fee_income_yoy_pct": _pct(cur.get("fee_income"), prev.get("fee_income")),
        "nim_approx_pct": _ratio(cur["nii"], cur.get("total_assets"), months),
        "cost_to_income_pct": _ratio(cur.get("opex"), cur.get("revenue")),
        "credit_cost_pct": _ratio(cur.get("credit_loss"), cur.get("loans"), months),
        "ldr_pct": _ratio(cur.get("loans"), cur.get("deposits")),
        "loans_mb": round(cur["loans"]) if cur.get("loans") is not None else None,
        "deposits_mb": round(cur["deposits"]) if cur.get("deposits") is not None else None,
    }


def financial_table(fins):
    """Table F: ต่อบริษัทที่มีงบ ค่าทั้งหมดคิดจากตัวเลขในงบที่ SET ให้มา"""
    rows = {}
    for name, f in fins.items():
        cur, prev = f["latest"], f.get("previous") or {}
        rev, np_ = cur.get("revenue"), cur.get("net_profit")
        full_years = [h for h in f.get("history", []) if h["period"] == "ทั้งปี"]
        fy = full_years[-1] if full_years else {}
        rows[name] = {
            "symbol": f.get("symbol"),
            "sector": (f.get("profile") or {}).get("sector"),
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
            **bank_metrics(cur, prev),
        }
    return pd.DataFrame.from_dict(rows, orient="index").rename_axis("company")


FINANCE_GAP_ITEMS = ("revenue_yoy_pct", "net_margin_pct", "roe_pct")


def internal_table(names):
    """Table I: ข้อมูลภายในที่ผู้ใช้อัปโหลด → ตาราง company × metric (หน่วย/ช่วงเวลาต่อ metric อยู่ใน attrs["units"])"""
    raw = db.internal_metrics(list(names))
    if raw.empty:
        return pd.DataFrame()
    table = raw.pivot_table(index="company", columns="metric", values="value", aggfunc="last")
    table = table.reindex([n for n in names if n in table.index])
    table.columns.name = None
    table.attrs["units"] = (raw.groupby("metric")[["unit", "period"]].last()
                            .fillna("").to_dict(orient="index"))
    return table


def gap_table(df, table_b, self_name, reviews=None, fin=None, members=(), internal=None):
    """ค่าของเรา − ค่าเฉลี่ยคู่แข่ง: category (% ของข่าวแต่ละบริษัท), sentiment (%), รีวิว (ดาว, % รีวิวลบ),
    การเงิน (% เติบโต, อัตรากำไร, ROE) · members = บริษัทในเครือ ไม่นับเป็นคู่แข่ง"""
    df = news_only(df)
    if df.empty or self_name not in set(df["company"]):
        return pd.DataFrame()
    share = pd.crosstab(df["company"], df["category"], normalize="index") * 100
    competitors = [c for c in share.index if c != self_name and c not in members]
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
    # ข้อมูลภายใน: หน่วยตามที่ผู้ใช้ให้มา ใช้เมื่อมีค่าของเราและคู่แข่งอย่างน้อย 1 ราย
    if internal is not None and not internal.empty and self_name in internal.index:
        for item in internal.columns:
            us = internal.loc[self_name, item]
            others = internal.loc[[c for c in competitors if c in internal.index], item].dropna()
            if pd.notna(us) and not others.empty:
                rows.append({"type": "internal", "item": item, "us_pct": round(float(us), 2),
                             "competitor_avg_pct": round(float(others.mean()), 2),
                             "gap_pts": round(float(us) - float(others.mean()), 2)})
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
                 [["company", "published_dt", "category", "sentiment", "summary", "title", "url"]]
                 .rename(columns={"published_dt": "date"}))
    table_c["date"] = table_c["date"].dt.strftime("%Y-%m-%d")
    return df, table_a, table_b, table_c


SET_FACTSHEET = "https://www.set.or.th/th/market/product/stock/quote/{}/financial-statement/company-highlights"
# [3] [1, 2] [6-10] และแบบที่ LLM ชอบเขียนเอง เช่น [Table C: ref 11-15] [ref 2]
REF = re.compile(r"\[(?:[A-Za-z][A-Za-z ]*:\s*)?(?:refs?\.?\s*)?(\d+(?:\s*[,，、\-–]\s*(?:refs?\.?\s*)?\d+)*)\]",
                 re.I)
# LLM บางครั้งอ้างชื่อตารางแทนเลข เช่น [Table F] [Gap table, Changes] ซึ่งผู้อ่านเปิดดูไม่ได้ จึงตัดทิ้ง
TABLE_CITE = re.compile(r"\s*\[(?:(?:Table\s*[A-Z]|Gap table|Changes|Group structure|Scope|Financials|Sector ranks|"
                        r"Stock moves[^]]*|Items)(?:\s*,\s*)?)+\](?!\()",
                        re.I)


def _changes_rows(changes, add_ref):
    rows = []
    for c in changes or []:
        url = c["items"][0]["url"] if c["items"] else None
        rows.append({"ref": add_ref(f"{c['company']}: {c['items'][0]['title']}", url) if url else "",
                     "company": c["company"], "level": c["level"], "change": c["text"],
                     "examples": " / ".join(it["title"] for it in c["items"][:3])})
    return pd.DataFrame(rows)


def link_refs(report, refs):
    """[3] → ลิงก์ไปยังแหล่งที่มา แล้วต่อท้ายรายการแหล่งอ้างอิงเฉพาะที่ถูกอ้างจริง"""
    used = []

    def numbers(text):
        out = []
        for part in re.split(r"[,，、]", text):
            ends = [int(x) for x in re.findall(r"\d+", part)]
            if len(ends) == 2 and 0 < ends[1] - ends[0] <= 10:  # ช่วง เช่น 6-10
                out += range(ends[0], ends[1] + 1)
            else:
                out += ends
        return out

    def repl(m):
        out = []
        for n in numbers(m.group(1)):
            if 1 <= n <= len(refs):
                out.append(f"[[{n}]]({refs[n - 1][1]})")
                used.append(n)
        return "".join(out) or m.group(0)

    report = REF.sub(repl, TABLE_CITE.sub("", report))
    if used:
        report += "\n\n---\n**แหล่งอ้างอิง**\n\n" + "\n".join(
            f"{n}. [{re.sub(r'[][]', '', refs[n - 1][0])[:120]}]({refs[n - 1][1]})" for n in sorted(set(used)))
    return report


def write_report(table_a, table_b, table_c, self_name=None, gap=None, mode=None, reviews=None, fin=None,
                 scope=None, groups=None, changes=None, internal=None, sector=None, price=None):
    """ไม่มี self_name = รายงานกลาง ๆ (phase1), มี self_name = มุมมองบริษัทเรา (phase2/phase3)
    scope = ข้อความบอกว่าข้อมูลถูกกรองเฉพาะเรื่อง/ช่วงไหน (ให้ LLM เขียนเน้นเรื่องนั้น)
    แถวใน Table C / F / Changes มีเลข ref ให้ LLM อ้างอิง แล้วแปลงเป็นลิงก์ไปยังข่าวหรืองบต้นทาง"""
    refs = []

    def add_ref(title, url):
        refs.append((title or url, url))
        return len(refs)

    c = table_c.copy()
    if "url" in c:
        c.insert(0, "ref", [add_ref(t, u) if isinstance(u, str) and u else ""
                            for t, u in zip(c["title"], c["url"])])
        c = c.drop(columns=["title", "url"])
    tables = dict(a=table_a.to_markdown(), b=table_b.to_markdown(), c=c.to_markdown(index=False))
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
        f = fin.dropna(axis=1, how="all").copy()
        if "symbol" in f:
            f.insert(0, "ref", [add_ref(f"งบการเงิน {name} ({sym}) จาก SET", SET_FACTSHEET.format(sym))
                                if isinstance(sym, str) and sym else "" for name, sym in zip(f.index, f["symbol"])])
        prompt += FINANCE_SECTION.format(f=f.to_markdown())
    if internal is not None and not internal.empty:
        units = pd.DataFrame.from_dict(internal.attrs.get("units", {}), orient="index")
        prompt += INTERNAL_SECTION.format(i=internal.to_markdown(), u=units.to_markdown())
    if sector is not None and not sector.empty:
        sref = {sym: add_ref(f"ตัวเลข {sym} จาก SET (เทียบหมวด{sec})", SET_FACTSHEET.format(sym))
                for sym, sec in sector[["symbol", "sector"]].drop_duplicates().itertuples(index=False)}
        s_tab = sector.assign(ref=sector["symbol"].map(sref))[
            ["ref", "company", "sector", "metric", "value", "rank", "n", "median"]]
        prompt += SECTOR_SECTION.format(s=s_tab.to_markdown(index=False))
    if price is not None and not price.empty and price["big"].any():
        p = price[price["big"]].head(8)
        p_tab = pd.DataFrame({
            "ref": [add_ref(t[0], u[0]) if u and u[0] else "" for t, u in zip(p["titles"], p["urls"])],
            "company": p["company"], "date": p["date"], "r1_pct": p["r1_pct"], "r3_pct": p["r3_pct"], "z": p["z"],
            "headlines": [" / ".join(t[:2])[:200] for t in p["titles"]]})
        prompt += PRICE_SECTION.format(p=p_tab.to_markdown(index=False))
    if changes:
        prompt += CHANGES_SECTION.format(ch=_changes_rows(changes, add_ref).to_markdown(index=False))
    if groups:
        prompt += GROUP_SECTION.format(g="\n".join(f"- {m} → {g['parent']} ({g['relation']})"
                                                   for m, g in groups.items()))
    if refs:
        prompt += CITE_RULE
    report = llm.chat(prompt).strip()
    if CJK.search(report):  # โมเดลบางครั้งหลุดคำภาษาจีนแม้สั่งไว้แล้ว ให้เขียนใหม่ 1 ครั้ง
        report = llm.chat(prompt + "\n\nIMPORTANT: Thai script only. Do not output any Chinese characters.").strip()
    report = link_refs(CJK.sub("", report), refs)
    db.save_report(mode, report)
    return report
