import json

import altair as alt
import pandas as pd
import requests
import streamlit as st

from core import analyze, collect, db, llm, process

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


def save_last_run(names, report_id):
    LAST_RUN.write_text(json.dumps({"companies": names, "report_id": report_id},
                                   ensure_ascii=False), encoding="utf-8")


def build_result(names, report_row):
    """รวมทุกอย่างที่หน้าผลลัพธ์ต้องใช้ (ตัวเลขทั้งหมดมาจาก analyze.build_tables)"""
    ids = db.company_ids(names)
    df, table_a, table_b, table_c = analyze.build_tables(ids)
    if not df.empty:
        df["หมวด"] = df["category"].map(CATEGORY_TH)
        df["น้ำเสียง"] = df["sentiment"].map(SENTIMENT_TH)
        df["วันที่"] = df["published_dt"].dt.strftime("%Y-%m-%d")
    return dict(
        companies=names, df=df, a=table_a, b=table_b, c=table_c,
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
    return build_result(last["companies"], report)


def run_pipeline(names, limit):
    calls_before = llm.call_count
    with st.status("กำลังวิเคราะห์...", expanded=True) as status:
        ids = [db.upsert_company(n, role="competitor", origin="user") for n in names]

        st.write("**1/3 ดึงข่าวจาก Google News**")
        empty = []
        for cid, name in zip(ids, names):
            fetched, added = collect.collect_company(cid, name, limit=limit)
            st.write(f"- {name}: {fetched} หัวข้อ (ใหม่ {added})")
            if fetched == 0:
                empty.append(name)

        st.write("**2/3 จัดหมวดข่าวด้วย LLM**")
        saved, skipped = process.classify_pending(ids, on_progress=lambda m: status.update(label=m))
        st.write(f"- จัดหมวดใหม่ {saved} ข่าว" + ("" if saved else " (ข่าวทั้งหมดเคยจัดหมวดแล้ว)"))
        if skipped:
            st.write(f"- ข้าม {skipped} ชุดที่ LLM ตอบรูปแบบไม่ถูก กดวิเคราะห์อีกครั้งเพื่อลองใหม่")

        df, table_a, table_b, table_c = analyze.build_tables(ids)
        if df.empty:
            status.update(label="ไม่พบข่าวของบริษัทที่เลือก", state="error")
            return None, empty

        status.update(label="เขียนรายงาน...")
        st.write("**3/3 เขียนรายงานสรุป**")
        analyze.write_report(table_a, table_b, table_c)
        report = db.latest_report("phase1")
        status.update(label=f"วิเคราะห์เสร็จ · เรียก LLM {llm.call_count - calls_before} ครั้ง",
                      state="complete", expanded=False)

    save_last_run(names, report["id"])
    return build_result(names, report), empty


# ---------- กราฟ ----------

def sentiment_chart(table_b):
    long = (table_b.rename(columns=SENTIMENT_TH).reset_index()
            .melt(id_vars="company", var_name="น้ำเสียง", value_name="สัดส่วน (%)"))
    long["ลำดับ"] = long["น้ำเสียง"].map({"บวก": 0, "กลาง": 1, "ลบ": 2})
    return (alt.Chart(long).mark_bar()
            .encode(
                x=alt.X("สัดส่วน (%):Q", stack="normalize", axis=alt.Axis(format="%", title=None)),
                y=alt.Y("company:N", title=None),
                color=alt.Color("น้ำเสียง:N",
                                scale=alt.Scale(domain=list(SENTIMENT_COLORS), range=list(SENTIMENT_COLORS.values())),
                                legend=alt.Legend(orient="bottom", title=None)),
                order="ลำดับ:Q",
                tooltip=["company", "น้ำเสียง", "สัดส่วน (%)"],
            )
            .properties(height=60 + 40 * len(table_b)))


def category_chart(df):
    counts = df.groupby(["company", "หมวด"]).size().reset_index(name="จำนวนข่าว")
    order = [CATEGORY_TH[k] for k in CATEGORY_TH if CATEGORY_TH[k] in set(counts["หมวด"])]
    return (alt.Chart(counts).mark_bar()
            .encode(
                x=alt.X("หมวด:N", sort=order, title=None, axis=alt.Axis(labelAngle=0)),
                xOffset="company:N",
                y=alt.Y("จำนวนข่าว:Q", title="จำนวนข่าว"),
                color=alt.Color("company:N", title="บริษัท", legend=alt.Legend(orient="bottom")),
                tooltip=["company", "หมวด", "จำนวนข่าว"],
            )
            .properties(height=340))


# ---------- ส่วนแสดงผล ----------

def empty_state():
    st.info("เลือกคู่แข่ง 2–5 รายที่แถบด้านซ้าย แล้วกด **เริ่มวิเคราะห์**")
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
    df, table_b = res["df"], res["b"]
    cols = st.columns(len(res["companies"]))
    for col, name in zip(cols, res["companies"]):
        with col.container(border=True):
            st.markdown(f"#### {name}")
            sub = df[df["company"] == name]
            if sub.empty:
                st.caption("ไม่พบข่าว")
                continue
            c1, c2, c3 = st.columns(3)
            c1.metric("ข่าว", len(sub))
            c2.metric("บวก", f"{table_b.loc[name, 'positive']:.0f}%")
            c3.metric("ลบ", f"{table_b.loc[name, 'negative']:.0f}%")
            top = sub["หมวด"].value_counts()
            st.caption(f"เน้นมากที่สุด: **{top.index[0]}** ({top.iloc[0]} ข่าว)")


def downloads(res):
    df = res["df"]
    csv = (df[["วันที่", "company", "หมวด", "น้ำเสียง", "title", "summary", "url"]]
           .rename(columns={"company": "บริษัท", "title": "หัวข้อข่าว", "summary": "สรุป", "url": "ลิงก์"})
           .to_csv(index=False).encode("utf-8-sig"))  # BOM ให้ Excel อ่านไทยได้
    c1, c2, _ = st.columns([1, 1, 3])
    c1.download_button("ดาวน์โหลดรายงาน (.md)", res["report"], "report.md", "text/markdown",
                       icon=":material/description:", width="stretch", on_click="ignore")
    c2.download_button("ดาวน์โหลดข่าว (.csv)", csv, "news.csv", "text/csv",
                       icon=":material/table:", width="stretch", on_click="ignore")


def tab_summary(res):
    left, right = st.columns([3, 2], gap="large")
    with left:
        st.markdown("##### รายงานสรุป")
        st.markdown(res["report"])
        st.caption(f"เขียนโดย LLM เมื่อ {fmt_time(res['report_at'])} จากตัวเลขในแท็บอื่นเท่านั้น")
    with right:
        st.markdown("##### น้ำเสียงข่าว")
        st.altair_chart(sentiment_chart(res["b"]), width="stretch")
        st.dataframe(res["b"].rename(columns=SENTIMENT_TH).rename_axis("บริษัท").map(lambda v: f"{v:.1f}%"),
                     width="stretch")


def tab_categories(res):
    st.altair_chart(category_chart(res["df"]), width="stretch")
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


def tab_all_news(res):
    df = res["df"]
    f1, f2, f3, f4 = st.columns([1, 1, 1, 1.4])
    companies = f1.multiselect("บริษัท", res["companies"], key="f_company", placeholder="ทั้งหมด")
    cats = f2.multiselect("หมวด", [v for v in CATEGORY_TH.values() if v in set(df["หมวด"])],
                          key="f_cat", placeholder="ทั้งหมด")
    sents = f3.multiselect("น้ำเสียง", list(SENTIMENT_COLORS), key="f_sent", placeholder="ทั้งหมด")
    query = f4.text_input("ค้นหาในหัวข้อ/สรุป", key="f_q", placeholder="เช่น 5G, กำไร")

    view = df
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

    st.caption(f"แสดง {len(view)} จาก {len(df)} ข่าว")
    st.dataframe(
        view.sort_values("published_dt", ascending=False),
        hide_index=True, width="stretch", height=480,
        column_order=["วันที่", "company", "หมวด", "น้ำเสียง", "title", "summary", "url"],
        column_config={
            "company": st.column_config.TextColumn("บริษัท"),
            "title": st.column_config.TextColumn("หัวข้อข่าว", width="large"),
            "summary": st.column_config.TextColumn("สรุป", width="large"),
            "url": st.column_config.LinkColumn("ลิงก์", display_text="เปิดข่าว"),
        },
    )


# ---------- หน้าเว็บ ----------

if "result" not in st.session_state:
    st.session_state.result = restore_last_result()
res = st.session_state.result

with st.sidebar:
    st.header("ตั้งค่าการวิเคราะห์")
    default = res["companies"] if res else DEFAULT_COMPANIES
    options = sorted(set(db.company_names()) | set(DEFAULT_COMPANIES) | set(default), key=str.lower)
    names = st.multiselect(
        "คู่แข่งที่ต้องการเทียบ", options, default=default,
        accept_new_options=True, max_selections=5,
        placeholder="พิมพ์ชื่อบริษัทแล้วกด Enter",
        help="เลือก 2–5 ราย พิมพ์ชื่อบริษัทใหม่ได้",
    )
    with st.expander("ตั้งค่าเพิ่มเติม"):
        limit = st.slider("จำนวนข่าวต่อบริษัท", 10, 50, 20, step=5,
                          help="จำนวนหัวข้อข่าวล่าสุดที่ดึงจาก Google News ต่อบริษัท")

    ready = 2 <= len(names) <= 5
    run = st.button("เริ่มวิเคราะห์", type="primary", disabled=not ready,
                    icon=":material/play_arrow:", width="stretch")
    if ready:
        st.caption("ใช้ LLM ประมาณ 1 ครั้งต่อข่าวใหม่ 10 ข่าว และอีก 1 ครั้งสำหรับรายงาน")
    else:
        st.caption("เลือกอย่างน้อย 2 บริษัทเพื่อเริ่ม")

st.title("Competitor Compare")

if run:
    try:
        new_res, empty = run_pipeline(names, limit)
        if empty:
            st.warning(f"ไม่พบข่าวของ: {', '.join(empty)} ลองตรวจตัวสะกดหรือใช้ชื่อที่สื่อใช้บ่อย")
        if new_res:
            st.session_state.result = res = new_res
    except RuntimeError as e:
        st.error(f"{e} เปิดไฟล์ `.env` ใส่ `LLM_API_KEY=...` แล้วรีสตาร์ทแอป")
    except requests.RequestException as e:
        st.error(f"เชื่อมต่อ LLM ไม่ได้ ({type(e).__name__}) ข่าวที่จัดหมวดแล้วถูกบันทึกไว้ "
                 "กดเริ่มวิเคราะห์อีกครั้งจะทำต่อจากเดิม")

if not res or res["df"].empty:
    empty_state()
    st.stop()

st.caption(f"{' · '.join(res['companies'])} · {len(res['df'])} ข่าว · "
           f"ข่าวอัปเดตล่าสุด {fmt_time(res['fetched_at'])}")
kpi_cards(res)
downloads(res)

t1, t2, t3, t4 = st.tabs(["สรุป", "หมวดข่าว", "ข่าวล่าสุด", "ข่าวทั้งหมด"])
with t1:
    tab_summary(res)
with t2:
    tab_categories(res)
with t3:
    tab_latest(res)
with t4:
    tab_all_news(res)
