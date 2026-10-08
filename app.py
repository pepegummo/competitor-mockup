import json
from contextlib import contextmanager

import altair as alt
import pandas as pd
import requests
import streamlit as st

from core import analyze, collect, db, discover, llm, process, profile
from core.sources import app_reviews

CATEGORY_TH = {
    "product_price": "สินค้า/ราคา",
    "promotion": "โปรโมชัน",
    "news_pr": "ข่าว/PR",
    "review": "รีวิว",
    "financial": "การเงิน",
    "hr": "บุคลากร",
    "other": "อื่น ๆ",
}
SENTIMENT_TH = {"positive": "บวก", "neutral": "กลาง", "negative": "ลบ"}
SENTIMENT_COLORS = {"บวก": "#2e9e5b", "กลาง": "#9aa0a6", "ลบ": "#d9534f"}
MODES = {
    "compare": ("เทียบคู่แข่ง", "เทียบคู่แข่งกันเอง รายงานกลาง ๆ"),
    "self": ("เรา vs คู่แข่ง", "มองจากมุมบริษัทเรา พร้อมข้อเสนอแนะ"),
    "discover": ("หาคู่แข่งให้", "บอกแค่บริษัทเรา ระบบหาคู่แข่งให้แล้วให้คุณยืนยัน"),
}
DEFAULT_COMPANIES = ["AIS", "True", "NT"]
LAST_RUN = db.DATA_DIR / "last_run.json"

st.set_page_config(page_title="Competitor Compare", page_icon="📊", layout="wide")
db.init_db()


# ---------- ข้อมูล ----------

def fmt_time(iso):
    return iso.replace("T", " ")[:16] if iso else "-"


def load_last_run():
    try:
        return json.loads(LAST_RUN.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def save_last_run(**data):
    LAST_RUN.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def build_result(companies, report_row, self_name=None, mode="compare"):
    """รวมทุกอย่างที่หน้าผลลัพธ์ต้องใช้ (ตัวเลขทั้งหมดมาจาก analyze)"""
    ids = db.company_ids(companies)
    df, table_a, table_b, table_c = analyze.build_tables(ids)
    gap, reviews = pd.DataFrame(), pd.DataFrame()
    if not df.empty:
        df["หมวด"] = df["category"].map(CATEGORY_TH)
        df["น้ำเสียง"] = df["sentiment"].map(SENTIMENT_TH)
        df["วันที่"] = df["published_dt"].dt.strftime("%Y-%m-%d")
        df["แหล่ง"] = df["source_type"].map(collect.SOURCE_TYPE_LABEL)
        reviews = analyze.review_table(df)
        if self_name and not table_b.empty:
            gap = analyze.gap_table(df, table_b, self_name, reviews)
    return dict(
        mode=mode, self_name=self_name, companies=companies,
        df=df, a=table_a, b=table_b, c=table_c, gap=gap, reviews=reviews,
        report=report_row["content_md"], report_at=report_row["created_at"],
        fetched_at=db.last_fetched_at(ids),
    )


def restore_last_result():
    last = load_last_run()
    if not last:
        return None
    report = db.get_report(last.get("report_id"))
    if not report or not db.company_ids(last.get("companies", [])):
        return None
    return build_result(last["companies"], report, last.get("self_name"), last.get("mode", "compare"))


def run_pipeline(competitors, limit, self_name=None, origins=None, mode="compare", opts=None):
    """self_name=None → Phase 1, มี self_name → Phase 2 (เรา vs คู่แข่ง)
    opts = {"sources": [...], "fulltext": bool, "review_limit": int} จากแถบ "แหล่งข้อมูล" """
    origins = origins or {}
    opts = opts or {"sources": ["google_news"], "fulltext": False, "review_limit": 20}
    companies = ([self_name] if self_name else []) + competitors
    calls_before = llm.call_count
    with st.status("กำลังวิเคราะห์...", expanded=True) as status:
        ids = []
        for name in companies:
            if name == self_name:
                ids.append(db.upsert_company(name, role="self", origin="user"))
            else:
                ids.append(db.upsert_company(name, role="competitor", origin=origins.get(name, "user")))

        labels = [collect.SOURCES[k][1] for k in opts["sources"]]
        st.write(f"**1/3 ดึงข้อมูล** ({', '.join(labels)})")
        if opts["fulltext"]:
            status.update(label="ดึงข้อมูลและเนื้อหาเต็ม (อาจใช้เวลาหลายนาที)...")
        empty = []
        for cid, name in zip(ids, companies):
            stats, notes = collect.collect_company(cid, name, limit=limit, sources=opts["sources"],
                                                   fulltext_on=opts["fulltext"], review_limit=opts["review_limit"])
            parts = [f"{label} {n} (ใหม่ {a})" for label, (n, a) in stats.items()]
            st.write(f"- **{name}**: " + (" · ".join(parts) or "ไม่มีแหล่งที่ใช้ได้"))
            for note in notes:
                st.caption(f"  {name} · {note}")
            if sum(n for label, (n, a) in stats.items() if label != "รีวิวแอป") == 0:
                empty.append(name)

        st.write("**2/3 จัดหมวดด้วย LLM**")
        saved, skipped = process.classify_pending(ids, on_progress=lambda m: status.update(label=m))
        st.write(f"- จัดหมวดใหม่ {saved} รายการ" + ("" if saved else " (ทั้งหมดเคยจัดหมวดแล้ว)"))
        if skipped:
            st.write(f"- ข้าม {skipped} ชุดที่ LLM ตอบรูปแบบไม่ถูก กดวิเคราะห์อีกครั้งเพื่อลองใหม่")

        df, table_a, table_b, table_c = analyze.build_tables(ids)
        if table_a.empty:
            status.update(label="ไม่พบข่าวของบริษัทที่เลือก", state="error")
            return None, empty

        status.update(label="เขียนรายงาน...")
        st.write("**3/3 เขียนรายงาน**")
        report_mode = "phase1" if not self_name else ("phase3" if mode == "discover" else "phase2")
        reviews = analyze.review_table(df)
        gap = analyze.gap_table(df, table_b, self_name, reviews) if self_name else None
        if self_name and (gap is None or gap.empty):
            # ไม่มีข่าวของเราหรือของคู่แข่ง → เขียนรายงานกลาง ๆ แทน
            st.write(f"- ไม่มีข่าวพอเทียบกับ {self_name} จึงเขียนรายงานแบบเทียบคู่แข่งแทน")
            self_name, report_mode = None, "phase1"
        analyze.write_report(table_a, table_b, table_c, self_name=self_name, gap=gap, mode=report_mode,
                             reviews=reviews)
        report = db.latest_report(report_mode)
        status.update(label=f"วิเคราะห์เสร็จ · เรียก LLM {llm.call_count - calls_before} ครั้ง",
                      state="complete", expanded=False)

    save_last_run(companies=companies, report_id=report["id"], self_name=self_name, mode=mode)
    return build_result(companies, report, self_name, mode), empty


# ---------- กราฟ ----------

def company_opacity(self_name):
    """ถ้ามีบริษัทเรา ให้แถบของเราเข้ม คู่แข่งจางลง"""
    if not self_name:
        return alt.value(1)
    return alt.condition(alt.datum.company == self_name, alt.value(1), alt.value(0.45))


def sentiment_chart(table_b, self_name=None):
    long = (table_b.rename(columns=SENTIMENT_TH).reset_index()
            .melt(id_vars="company", var_name="น้ำเสียง", value_name="สัดส่วน (%)"))
    long["ลำดับ"] = long["น้ำเสียง"].map({"บวก": 0, "กลาง": 1, "ลบ": 2})
    order = ([self_name] if self_name else []) + [c for c in table_b.index if c != self_name]
    return (alt.Chart(long).mark_bar()
            .encode(
                x=alt.X("สัดส่วน (%):Q", stack="normalize", axis=alt.Axis(format="%", title=None)),
                y=alt.Y("company:N", title=None, sort=order),
                color=alt.Color("น้ำเสียง:N",
                                scale=alt.Scale(domain=list(SENTIMENT_COLORS), range=list(SENTIMENT_COLORS.values())),
                                legend=alt.Legend(orient="bottom", title=None)),
                opacity=company_opacity(self_name),
                order="ลำดับ:Q",
                tooltip=["company", "น้ำเสียง", "สัดส่วน (%)"],
            )
            .properties(height=60 + 40 * len(table_b)))


def category_chart(df, self_name=None):
    counts = df.groupby(["company", "หมวด"]).size().reset_index(name="จำนวนข่าว")
    order = [v for v in CATEGORY_TH.values() if v in set(counts["หมวด"])]
    companies = ([self_name] if self_name else []) + sorted(c for c in counts["company"].unique() if c != self_name)
    return (alt.Chart(counts).mark_bar()
            .encode(
                x=alt.X("หมวด:N", sort=order, title=None, axis=alt.Axis(labelAngle=0)),
                xOffset=alt.XOffset("company:N", sort=companies),
                y=alt.Y("จำนวนข่าว:Q", title="จำนวนข่าว"),
                color=alt.Color("company:N", title="บริษัท", sort=companies,
                                legend=alt.Legend(orient="bottom")),
                opacity=company_opacity(self_name),
                tooltip=["company", "หมวด", "จำนวนข่าว"],
            )
            .properties(height=340))


def gap_chart(gap, kind, self_name):
    data = gap[gap["type"] == kind].copy()
    labels = CATEGORY_TH if kind == "category" else SENTIMENT_TH
    data["รายการ"] = data["item"].map(labels)
    if kind == "category":
        # หมวด: มาก/น้อยกว่าไม่ได้แปลว่าดี/แย่ แค่บอกว่าเราเน้นต่างจากคู่แข่ง
        data["ผล"] = data["gap_pts"].map(lambda g: f"{self_name} เน้นมากกว่า" if g >= 0 else f"{self_name} เน้นน้อยกว่า")
        domain = [f"{self_name} เน้นมากกว่า", f"{self_name} เน้นน้อยกว่า"]
        colors = ["#2557a7", "#e08a2b"]
    else:
        # น้ำเสียง: ข่าวบวกมากกว่า = ดี, ข่าวลบมากกว่า = แย่
        good = data.apply(lambda r: r["gap_pts"] >= 0 if r["item"] != "negative" else r["gap_pts"] <= 0, axis=1)
        data["ผล"] = good.map({True: "ดีกว่าคู่แข่ง", False: "แย่กว่าคู่แข่ง"})
        domain, colors = ["ดีกว่าคู่แข่ง", "แย่กว่าคู่แข่ง"], ["#2e9e5b", "#d9534f"]
    return (alt.Chart(data).mark_bar()
            .encode(
                x=alt.X("gap_pts:Q", title="ส่วนต่าง (จุด %)"),
                y=alt.Y("รายการ:N", title=None, sort=list(labels.values())),
                color=alt.Color("ผล:N", scale=alt.Scale(domain=domain, range=colors),
                                legend=alt.Legend(orient="bottom", title=None)),
                tooltip=[alt.Tooltip("รายการ:N"), alt.Tooltip("us_pct:Q", title="เรา (%)"),
                         alt.Tooltip("competitor_avg_pct:Q", title="คู่แข่งเฉลี่ย (%)"),
                         alt.Tooltip("gap_pts:Q", title="ส่วนต่าง (จุด)")],
            )
            .properties(height=40 + 32 * len(data)))


# ---------- ส่วนแสดงผล ----------

def empty_state():
    st.info("เลือกโหมดและบริษัทที่แถบด้านซ้าย แล้วกด **เริ่มวิเคราะห์**")
    cols = st.columns(3)
    steps = [
        ("1. ดึงข่าว", "ดึงหัวข้อข่าวล่าสุดของแต่ละบริษัทจาก Google News"),
        ("2. จัดหมวด", "ให้ LLM แยกหมวดและน้ำเสียงข่าว (บวก/กลาง/ลบ) ข่าวที่เคยจัดแล้วจะไม่ถูกส่งซ้ำ"),
        ("3. สรุปผล", "นับตัวเลขเปรียบเทียบ แล้วให้ LLM เขียนรายงานจากตัวเลขนั้น"),
    ]
    for col, (title, text) in zip(cols, steps):
        with col.container(border=True):
            st.markdown(f"**{title}**")
            st.caption(text)


def kpi_cards(res):
    df, table_b, self_name = res["df"], res["b"], res["self_name"]
    competitors = [c for c in res["companies"] if c != self_name and c in table_b.index]
    cols = st.columns(len(res["companies"]))
    for col, name in zip(cols, res["companies"]):
        with col.container(border=True):
            is_self = name == self_name
            st.markdown(f"#### {name}" + ("  :blue-badge[บริษัทเรา]" if is_self else ""))
            sub = analyze.news_only(df)[lambda d: d["company"] == name]
            if sub.empty or name not in table_b.index:
                st.caption("ไม่พบข่าว")
                continue
            pos, neg = table_b.loc[name, "positive"], table_b.loc[name, "negative"]
            pos_delta = neg_delta = None
            if is_self and competitors:
                pos_delta = f"{pos - table_b.loc[competitors, 'positive'].mean():+.0f} จุด"
                neg_delta = f"{neg - table_b.loc[competitors, 'negative'].mean():+.0f} จุด"
            c1, c2, c3 = st.columns(3)
            c1.metric("ข่าว", len(sub))
            c2.metric("บวก", f"{pos:.0f}%", pos_delta)
            c3.metric("ลบ", f"{neg:.0f}%", neg_delta, delta_color="inverse")
            top = sub["หมวด"].value_counts()
            st.caption(f"เน้นมากที่สุด: **{top.index[0]}** ({top.iloc[0]} ข่าว)")
            reviews = res.get("reviews", pd.DataFrame())
            if not reviews.empty and name in reviews.index:
                r = reviews.loc[name]
                st.caption(f"รีวิวแอป ★ **{r['avg_stars']:.1f}** จาก {int(r['reviews'])} รีวิว "
                           f"(รีวิวลบ {r['negative_pct']:.0f}%)")
            if is_self and competitors:
                st.caption("ตัวเลขใต้ % คือส่วนต่างจากค่าเฉลี่ยคู่แข่ง")


def downloads(res):
    df = res["df"]
    csv = (df[["วันที่", "company", "แหล่ง", "source_name", "หมวด", "น้ำเสียง", "rating", "title", "summary", "url"]]
           .rename(columns={"company": "บริษัท", "source_name": "ที่มา", "rating": "ดาว",
                            "title": "หัวข้อ", "summary": "สรุป", "url": "ลิงก์"})
           .to_csv(index=False).encode("utf-8-sig"))  # BOM ให้ Excel อ่านไทยได้
    c1, c2, _ = st.columns([1, 1, 3])
    c1.download_button("ดาวน์โหลดรายงาน (.md)", res["report"], "report.md", "text/markdown",
                       icon=":material/description:", width="stretch", on_click="ignore")
    c2.download_button("ดาวน์โหลดข้อมูล (.csv)", csv, "data.csv", "text/csv",
                       icon=":material/table:", width="stretch", on_click="ignore")


def tab_summary(res):
    left, right = st.columns([3, 2], gap="large")
    with left:
        title = f"ข้อเสนอแนะสำหรับ {res['self_name']}" if res["self_name"] else "รายงานสรุป"
        st.markdown(f"##### {title}")
        st.markdown(res["report"])
        st.caption(f"เขียนโดย LLM เมื่อ {fmt_time(res['report_at'])} จากตัวเลขในแท็บอื่นเท่านั้น")
    with right:
        st.markdown("##### น้ำเสียงข่าว")
        st.altair_chart(sentiment_chart(res["b"], res["self_name"]), width="stretch")
        st.dataframe(res["b"].rename(columns=SENTIMENT_TH).rename_axis("บริษัท").map(lambda v: f"{v:.1f}%"),
                     width="stretch")


def tab_gap(res):
    gap, self_name = res["gap"], res["self_name"]
    st.caption(f"{self_name} เทียบกับค่าเฉลี่ยของคู่แข่ง หมวดข่าวคิดเป็น % ของข่าวทั้งหมดของแต่ละบริษัท "
               "จึงเทียบกันได้แม้จำนวนข่าวไม่เท่ากัน")
    left, right = st.columns(2, gap="large")
    with left:
        st.markdown("##### หมวดข่าว: เราเน้นต่างจากคู่แข่งตรงไหน")
        st.altair_chart(gap_chart(gap, "category", self_name), width="stretch")
    with right:
        st.markdown("##### น้ำเสียงข่าว: เราดีหรือแย่กว่า")
        st.altair_chart(gap_chart(gap, "sentiment", self_name), width="stretch")
    table = gap.copy()
    table["type"] = table["type"].map({"category": "หมวด", "sentiment": "น้ำเสียง", "review": "รีวิวแอป"})
    table["item"] = table["item"].map({**CATEGORY_TH, **SENTIMENT_TH,
                                       "avg_stars": "คะแนนเฉลี่ย (ดาว)", "negative_pct": "รีวิวลบ (%)"})
    st.dataframe(
        table.rename(columns={"type": "ประเภท", "item": "รายการ", "us_pct": f"{self_name} (%)",
                              "competitor_avg_pct": "คู่แข่งเฉลี่ย (%)", "gap_pts": "ส่วนต่าง (จุด)"}),
        hide_index=True, width="stretch",
    )
    if (gap["type"] == "review").any():
        st.caption("แถวรีวิวแอป: คะแนนเฉลี่ยเป็นดาว (1–5) ไม่ใช่ % ส่วนรีวิวลบยิ่งน้อยยิ่งดี")


def tab_categories(res):
    st.altair_chart(category_chart(analyze.news_only(res["df"]), res["self_name"]), width="stretch")
    table_a = res["a"].rename(columns=CATEGORY_TH).rename_axis(index="บริษัท", columns=None)
    st.dataframe(table_a, width="stretch")
    st.caption("ตัวเลขคือจำนวนข่าว แถวและคอลัมน์ “รวม” คือผลรวม")


def tab_latest(res):
    c = res["c"].copy()
    c["category"] = c["category"].map(CATEGORY_TH)
    c["sentiment"] = c["sentiment"].map(SENTIMENT_TH)
    c = c.rename(columns={"company": "บริษัท", "date": "วันที่", "category": "หมวด",
                          "sentiment": "น้ำเสียง", "summary": "สรุป"})
    st.dataframe(c, hide_index=True, width="stretch")


def tab_reviews(res):
    df, reviews = res["df"], res["reviews"]
    r = df[df["source_type"] == "review"]
    st.caption("รีวิวล่าสุดจาก App Store และ Google Play ของแอปที่ตั้งค่าไว้ในแต่ละบริษัท "
               "คะแนนดาวมาจากผู้รีวิวโดยตรง ส่วนน้ำเสียงและสรุปมาจาก LLM")
    left, right = st.columns(2, gap="large")
    with left:
        st.markdown("##### คะแนนเฉลี่ย (ดาว)")
        stars = r.groupby(["company", "source_name"])["rating"].mean().round(2).reset_index()
        st.altair_chart(
            alt.Chart(stars).mark_bar().encode(
                x=alt.X("rating:Q", title="ดาวเฉลี่ย", scale=alt.Scale(domain=[0, 5])),
                y=alt.Y("company:N", title=None),
                yOffset="source_name:N",
                color=alt.Color("source_name:N", title=None, legend=alt.Legend(orient="bottom")),
                opacity=company_opacity(res["self_name"]),
                tooltip=["company", "source_name", "rating"],
            ).properties(height=60 + 50 * stars["company"].nunique()),
            width="stretch")
    with right:
        st.markdown("##### น้ำเสียงของรีวิว")
        sent = (pd.crosstab(r["company"], r["sentiment"], normalize="index") * 100).round(1)
        sent = sent.reindex(columns=["positive", "neutral", "negative"], fill_value=0)
        st.altair_chart(sentiment_chart(sent, res["self_name"]), width="stretch")
    st.dataframe(
        reviews.rename(columns={"reviews": "จำนวนรีวิว", "avg_stars": "ดาวเฉลี่ย",
                                "avg_stars_app_store": "App Store", "avg_stars_google_play": "Google Play",
                                "positive_pct": "รีวิวบวก (%)", "negative_pct": "รีวิวลบ (%)"})
               .rename_axis("บริษัท"),
        width="stretch")
    st.markdown("##### รีวิวล่าสุด")
    st.dataframe(
        r.sort_values("published_dt", ascending=False),
        hide_index=True, width="stretch", height=420,
        column_order=["วันที่", "company", "source_name", "rating", "น้ำเสียง", "content", "summary"],
        column_config={
            "company": st.column_config.TextColumn("บริษัท"),
            "source_name": st.column_config.TextColumn("สโตร์"),
            "rating": st.column_config.NumberColumn("ดาว", format="%d ★"),
            "content": st.column_config.TextColumn("รีวิว", width="large"),
            "summary": st.column_config.TextColumn("สรุป", width="medium"),
        },
    )


def tab_all_news(res):
    df = res["df"]
    f0, f1, f2, f3, f4 = st.columns([1, 1, 1, 1, 1.4])
    srcs = f0.multiselect("แหล่ง", [v for v in collect.SOURCE_TYPE_LABEL.values() if v in set(df["แหล่ง"])],
                          key="f_src", placeholder="ทั้งหมด")
    companies = f1.multiselect("บริษัท", res["companies"], key="f_company", placeholder="ทั้งหมด")
    cats = f2.multiselect("หมวด", [v for v in CATEGORY_TH.values() if v in set(df["หมวด"])],
                          key="f_cat", placeholder="ทั้งหมด")
    sents = f3.multiselect("น้ำเสียง", list(SENTIMENT_COLORS), key="f_sent", placeholder="ทั้งหมด")
    query = f4.text_input("ค้นหาในหัวข้อ/สรุป", key="f_q", placeholder="เช่น 5G, กำไร")

    view = df
    if srcs:
        view = view[view["แหล่ง"].isin(srcs)]
    if companies:
        view = view[view["company"].isin(companies)]
    if cats:
        view = view[view["หมวด"].isin(cats)]
    if sents:
        view = view[view["น้ำเสียง"].isin(sents)]
    if query:
        q = query.strip().lower()
        view = view[view["title"].str.lower().str.contains(q, regex=False)
                    | view["summary"].str.lower().str.contains(q, regex=False)]

    st.caption(f"แสดง {len(view)} จาก {len(df)} รายการ")
    st.dataframe(
        view.sort_values("published_dt", ascending=False),
        hide_index=True, width="stretch", height=480,
        column_order=["วันที่", "company", "แหล่ง", "source_name", "หมวด", "น้ำเสียง", "title", "summary", "url"],
        column_config={
            "company": st.column_config.TextColumn("บริษัท"),
            "source_name": st.column_config.TextColumn("ที่มา"),
            "title": st.column_config.TextColumn("หัวข้อ", width="large"),
            "summary": st.column_config.TextColumn("สรุป", width="large"),
            "url": st.column_config.LinkColumn("ลิงก์", display_text="เปิด"),
        },
    )


def show_results(res):
    counts = res["df"]["แหล่ง"].value_counts()
    st.caption(f"{' · '.join(res['companies'])} · "
               + " · ".join(f"{label} {n}" for label, n in counts.items())
               + f" · อัปเดตล่าสุด {fmt_time(res['fetched_at'])}")
    kpi_cards(res)
    downloads(res)

    has_gap = res["self_name"] and not res["gap"].empty
    has_reviews = not res.get("reviews", pd.DataFrame()).empty
    tabs = (["สรุป"] + (["เรา vs คู่แข่ง"] if has_gap else []) + ["หมวดข่าว"]
            + (["รีวิวแอป"] if has_reviews else []) + ["ข่าวล่าสุด", "ข้อมูลทั้งหมด"])
    renderers = ([tab_summary] + ([tab_gap] if has_gap else []) + [tab_categories]
                 + ([tab_reviews] if has_reviews else []) + [tab_latest, tab_all_news])
    for tab, render in zip(st.tabs(tabs), renderers):
        with tab:
            render(res)


# ---------- ตั้งค่าแหล่งข้อมูลของแต่ละบริษัท ----------

SOURCE_COLS = {"name": "บริษัท", "aliases": "ชื่อที่ใช้ค้นในข่าว (คั่นด้วย ,)", "appstore_id": "App Store id",
               "play_app_id": "Google Play id", "website": "URL หน้าข่าว/โปรโมชันของบริษัท"}


def source_settings(names):
    """ตารางแก้ไขชื่อเรียก แอป และเว็บไซต์ของบริษัทที่เลือก พร้อมปุ่มหาอัตโนมัติ"""
    if not names:
        return
    with st.expander("แหล่งข้อมูลของแต่ละบริษัท (ชื่อเรียก, แอป, เว็บไซต์)"):
        st.caption("ใช้กับแหล่ง “สำนักข่าวไทย” (จับข่าวจากชื่อเรียก), “รีวิวแอป” และ “เว็บไซต์บริษัท” "
                   "กดหาอัตโนมัติแล้วตรวจก่อนบันทึก เพราะแอปที่หาได้อาจไม่ใช่ของบริษัทนั้น")
        if st.session_state.get("source_draft", {}).get("names") != names:
            # บริษัทที่ยังไม่มีใน DB แสดงเป็นแถวว่าง จะถูกสร้างเมื่อกดบันทึก
            saved = {r["name"]: r for r in db.get_companies(names)}
            empty = {"aliases": [], "appstore_id": None, "play_app_id": None, "website": None}
            st.session_state.source_draft = {"names": names, "rows": [
                {"name": n, "aliases": ", ".join(r["aliases"]), "appstore_id": r["appstore_id"] or "",
                 "play_app_id": r["play_app_id"] or "", "website": r["website"] or ""}
                for n in names for r in [saved.get(n, empty)]]}
        draft = st.session_state.source_draft

        c1, c2, _ = st.columns([1.3, 1, 2])
        if c1.button("หาแอปและชื่อเรียกอัตโนมัติ", icon=":material/auto_fix_high:"):
            with friendly_errors(), st.spinner("กำลังค้นหาแอปและชื่อเรียก..."):
                aliases = profile.suggest_aliases(names)
                found_notes = []
                for row in draft["rows"]:
                    found = app_reviews.search_apps(row["name"])
                    row["appstore_id"] = row["appstore_id"] or found.get("appstore_id", "")
                    row["play_app_id"] = row["play_app_id"] or found.get("play_app_id", "")
                    if not row["aliases"] and aliases.get(row["name"]):
                        row["aliases"] = ", ".join(aliases[row["name"]])
                    found_notes.append(f"{row['name']}: App Store “{found.get('appstore_name', '-')}” · "
                                       f"Google Play “{found.get('play_name', '-')}”")
                draft["found"] = found_notes
                st.session_state.source_editor_v = st.session_state.get("source_editor_v", 0) + 1
        for note in draft.get("found", []):
            st.caption(note)

        edited = st.data_editor(
            pd.DataFrame(draft["rows"]), hide_index=True, width="stretch",
            key=f"source_editor_{st.session_state.get('source_editor_v', 0)}",
            disabled=["name"], column_config={k: st.column_config.TextColumn(v) for k, v in SOURCE_COLS.items()},
        )
        if c2.button("บันทึก", icon=":material/save:"):
            for _, row in edited.iterrows():
                aliases = [a.strip() for a in str(row["aliases"] or "").split(",") if a.strip()]
                db.update_company_sources(row["name"], aliases, str(row["play_app_id"] or "").strip(),
                                          str(row["appstore_id"] or "").strip(), str(row["website"] or "").strip())
            st.session_state.pop("source_draft", None)
            st.toast("บันทึกแหล่งข้อมูลแล้ว")


# ---------- Phase 3: ยืนยันรายชื่อคู่แข่ง ----------

@contextmanager
def friendly_errors():
    try:
        yield
    except RuntimeError as e:
        st.error(f"{e} เปิดไฟล์ `.env` ใส่ `LLM_API_KEY=...` แล้วรีสตาร์ทแอป")
    except requests.RequestException as e:
        st.error(f"เชื่อมต่อ LLM ไม่ได้ ({type(e).__name__}) ข่าวที่จัดหมวดแล้วถูกบันทึกไว้ "
                 "กดอีกครั้งจะทำต่อจากเดิม")


def confirm_panel(disc):
    """แสดงรายชื่อที่ระบบหาได้ ให้ผู้ใช้ติ๊กเลือก/เพิ่มเอง คืน (กดยืนยันไหม, รายชื่อ, origins)"""
    r = disc["result"]
    st.subheader(f"คู่แข่งที่พบสำหรับ {disc['company']}")
    if not r["found"]:
        st.warning(r["message"])
        return False, [], {}
    st.caption(f"{r['message']} · ติ๊กเฉพาะรายที่ใช่ แล้วกดยืนยัน "
               "ถ้ารายชื่อผิด ผลวิเคราะห์ที่ตามมาจะผิดทั้งหมด")

    picked = []
    for i, c in enumerate(r["candidates"]):
        with st.container(border=True):
            check = st.checkbox(f"**{c['name']}**", value=not c["no_evidence"], key=f"cand_{disc['id']}_{i}")
            badges = [f":violet-badge[{s}]" if s == "LLM" else f":blue-badge[{s}]" for s in c["sources"]]
            if c["no_evidence"]:
                badges.append(":red-badge[ไม่พบหลักฐาน]")
            co = "20+" if c["co_mentions"] >= 20 else c["co_mentions"]
            st.markdown(" ".join(badges) + f" · ข่าวที่พูดถึงคู่กับ {disc['company']}: {co} ข่าว")
            if c["reason"]:
                st.caption(c["reason"])
            if c["evidence"]:
                st.markdown("\n".join(f"- [{e['title']}]({e['url']})" for e in c["evidence"]))
            if check:
                picked.append(c["name"])

    extra = st.text_input("เพิ่มคู่แข่งเอง (คั่นด้วย ,)", key=f"extra_{disc['id']}", placeholder="เช่น dtac, Jasmine")
    typed = [n.strip() for n in extra.split(",") if n.strip() and n.strip() not in picked]
    names = picked + typed
    too_many = len(names) > 10
    ok = st.button(f"ยืนยันและวิเคราะห์ ({len(names)} ราย)", type="primary",
                   disabled=not names or too_many, icon=":material/check:")
    if too_many:
        st.caption("เลือกได้สูงสุด 10 ราย")
    origins = {n: "discovered" for n in picked} | {n: "user" for n in typed}
    return ok, names, origins


# ---------- หน้าเว็บ ----------

if "result" not in st.session_state:
    st.session_state.result = restore_last_result()
res = st.session_state.result
run = find = False

# ค่าเริ่มต้นของช่องกรอก ตั้งครั้งเดียวต่อ session (widget ใช้ key คงที่ ค่าจะไม่รีเซ็ตเองหลังวิเคราะห์)
if "mode_input" not in st.session_state:
    st.session_state.mode_input = res["mode"] if res and res["mode"] in MODES else "compare"
    st.session_state.self_input = (res or {}).get("self_name") or ""
    st.session_state.comp_input = [c for c in (res["companies"] if res else DEFAULT_COMPANIES)
                                   if c != (res or {}).get("self_name")][:5]

with st.sidebar:
    st.header("ตั้งค่าการวิเคราะห์")
    mode_keys = list(MODES)
    mode = st.radio("โหมด", mode_keys, format_func=lambda k: MODES[k][0],
                    captions=[MODES[k][1] for k in mode_keys], key="mode_input")

    self_name = None
    if mode in ("self", "discover"):
        self_name = st.text_input("บริษัทของเรา", key="self_input", placeholder="เช่น AIS").strip() or None

    if mode == "discover":
        top_x = st.slider("จำนวนคู่แข่งที่ต้องการ", 3, 10, 5)
        industry = st.text_input("อุตสาหกรรม (ไม่บังคับ)", placeholder="เช่น โทรคมนาคม, ส่งอาหาร")
        country = st.text_input("ประเทศ", "ประเทศไทย")
    else:
        options = sorted(set(db.company_names()) | set(DEFAULT_COMPANIES) | set(st.session_state.comp_input),
                         key=str.lower)
        competitors = st.multiselect(
            "คู่แข่งที่ต้องการเทียบ", options, key="comp_input",
            accept_new_options=True, max_selections=5,
            placeholder="พิมพ์ชื่อบริษัทแล้วกด Enter",
            help="เลือก 2–5 ราย พิมพ์ชื่อบริษัทใหม่ได้",
        )
        competitors = [c for c in competitors if c != self_name]

    with st.expander("แหล่งข้อมูล"):
        chosen = [key for key, (_, label) in collect.SOURCES.items()
                  if st.checkbox(label, value=True, key=f"src_{key}")]
        full = st.checkbox("ดึงเนื้อหาเต็มของข่าว", value=False, key="src_fulltext",
                           help="เปิดลิงก์ข่าวแต่ละข่าวเพื่ออ่านเนื้อหา ทำให้สรุปแม่นขึ้น แต่ช้าลงหลายนาที "
                                "และใช้ LLM มากขึ้น (ส่งทีละ 5 ข่าวแทน 10)")
        st.caption("รีวิวแอปและเว็บไซต์บริษัทต้องตั้งค่าในหัวข้อ “แหล่งข้อมูลของแต่ละบริษัท” ในหน้าหลักก่อน")
    with st.expander("ตั้งค่าเพิ่มเติม"):
        limit = st.slider("จำนวนข่าวต่อบริษัท ต่อแหล่ง", 10, 50, 20, step=5,
                          help="จำนวนรายการสูงสุดที่ดึงจากแต่ละแหล่งข่าวต่อบริษัท")
        review_limit = st.slider("จำนวนรีวิวต่อแอป", 10, 50, 20, step=5,
                                 help="รีวิวล่าสุดต่อแอปต่อสโตร์ ยิ่งมากยิ่งใช้ LLM มาก")
    opts = {"sources": chosen, "fulltext": full, "review_limit": review_limit}

    if mode == "discover":
        find = st.button("หาคู่แข่ง", type="primary", disabled=not self_name,
                         icon=":material/search:", width="stretch")
        st.caption("ใช้ LLM 3 ครั้ง + ค้นข่าว แล้วให้คุณยืนยันรายชื่อก่อนวิเคราะห์"
                   if self_name else "กรอกชื่อบริษัทของเราเพื่อเริ่ม")
    else:
        problems = []
        if mode == "self" and not self_name:
            problems.append("กรอกชื่อบริษัทของเรา")
        if not 2 <= len(competitors) <= 5:
            problems.append("เลือกคู่แข่ง 2–5 ราย (ไม่นับบริษัทเรา)")
        if not chosen:
            problems.append("เลือกแหล่งข้อมูลอย่างน้อย 1 แหล่ง")
        run = st.button("เริ่มวิเคราะห์", type="primary", disabled=bool(problems),
                        icon=":material/play_arrow:", width="stretch")
        st.caption(" และ ".join(problems) + " เพื่อเริ่ม" if problems
                   else "ใช้ LLM ประมาณ 1 ครั้งต่อข่าวใหม่ 10 ข่าว และอีก 1 ครั้งสำหรับรายงาน")

st.title("Competitor Compare")


def finish(new_res, empty):
    if empty:
        st.warning(f"ไม่พบข่าวของ: {', '.join(empty)} ลองตรวจตัวสะกดหรือใช้ชื่อที่สื่อใช้บ่อย")
    if new_res:
        st.session_state.result = new_res
    return st.session_state.result


if run:
    with friendly_errors():
        res = finish(*run_pipeline(competitors, limit, self_name=self_name, mode=mode, opts=opts))

if find:
    with friendly_errors():
        with st.status(f"กำลังหาคู่แข่งของ {self_name}...", expanded=True) as status:
            found = discover.discover(self_name, top_x, country.strip() or "ประเทศไทย",
                                      industry.strip() or None, on_progress=st.write)
            status.update(label=found["message"], state="complete" if found["found"] else "error",
                          expanded=False)
        st.session_state.discovery = {"id": st.session_state.get("discovery", {}).get("id", 0) + 1,
                                      "company": self_name, "result": found, "pending": True}

# บริษัทที่จะวิเคราะห์ในรอบถัดไป ใช้กับตารางตั้งค่าแหล่งข้อมูล
disc = st.session_state.get("discovery")
if mode == "discover":
    upcoming = [disc["company"]] + [c["name"] for c in disc["result"]["candidates"]] if disc else []
else:
    upcoming = ([self_name] if self_name else []) + competitors
source_settings(list(dict.fromkeys(upcoming)))

if mode == "discover" and disc and disc["pending"]:
    panel = st.empty()
    with panel.container():
        confirmed, names, origins = confirm_panel(disc)
    if not confirmed:
        st.stop()
    panel.empty()
    with friendly_errors():
        res = finish(*run_pipeline(names, limit, self_name=disc["company"], origins=origins, mode="discover",
                                   opts=opts))
        disc["pending"] = False

if not res or res["df"].empty:
    empty_state()
    st.stop()

show_results(res)
