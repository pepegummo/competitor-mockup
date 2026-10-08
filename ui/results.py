"""หน้าผลลัพธ์: แถบตัวกรอง (กรองทุกกราฟ/ตาราง) → การ์ดสรุปต่อบริษัท → 4 แท็บ"""
from datetime import datetime, timedelta, timezone

import pandas as pd
import streamlit as st

from core import analyze, collect, db
from ui import charts, insights
from ui.common import fmt_time, friendly_errors
from ui.labels import CATEGORY_TH, GAP_ITEM_TH, GAP_TYPE_TH, GLOSSARY, SENTIMENT_COLORS, SENTIMENT_TH

PERIODS = {"7 วัน": 7, "30 วัน": 30, "90 วัน": 90, "ทั้งหมด": None}
FILTER_KEYS = ("flt_company", "flt_src", "flt_days", "flt_cat", "flt_sent", "flt_q")


def reset_filters():
    for k in FILTER_KEYS:
        st.session_state.pop(k, None)


# ---------- ตัวกรอง ----------

def filter_bar(res):
    df = res["df"]
    with st.container(border=True):
        c1, c2, c3 = st.columns([2, 2, 1.6])
        companies = c1.multiselect("บริษัท", res["companies"], key="flt_company", placeholder="ทุกบริษัท")
        sources = c2.multiselect("แหล่ง", [v for v in collect.SOURCE_TYPE_LABEL.values() if v in set(df["แหล่ง"])],
                                 key="flt_src", placeholder="ทุกแหล่ง")
        period = c3.segmented_control("ช่วงเวลา", list(PERIODS), key="flt_days", default="ทั้งหมด")
        c4, c5, c6, c7 = st.columns([3, 1.4, 1.8, 0.8], vertical_alignment="bottom")
        cats = c4.pills("หมวด", [v for v in CATEGORY_TH.values() if v in set(df["หมวด"])],
                        selection_mode="multi", key="flt_cat")
        sents = c5.pills("น้ำเสียง", list(SENTIMENT_COLORS), selection_mode="multi", key="flt_sent")
        query = c6.text_input("ค้นหาคำ", key="flt_q", placeholder="เช่น 5G, กำไร")
        c7.button("ล้าง", icon=":material/filter_alt_off:", on_click=reset_filters, width="stretch",
                  help="ล้างตัวกรองทั้งหมด")
    return {"companies": companies, "sources": sources, "days": PERIODS.get(period or "ทั้งหมด"),
            "period": period, "categories": cats or [], "sentiments": sents or [], "query": query.strip()}


def describe(f):
    parts = []
    if f["companies"]:
        parts.append("บริษัท " + ", ".join(f["companies"]))
    if f["sources"]:
        parts.append("แหล่ง " + ", ".join(f["sources"]))
    if f["days"]:
        parts.append(f"{f['period']}ล่าสุด")
    if f["categories"]:
        parts.append("หมวด " + ", ".join(f["categories"]))
    if f["sentiments"]:
        parts.append("น้ำเสียง " + ", ".join(f["sentiments"]))
    if f["query"]:
        parts.append(f"คำว่า “{f['query']}”")
    return " · ".join(parts)


def apply_filters(df, f):
    v = df
    if f["companies"]:
        v = v[v["company"].isin(f["companies"])]
    if f["sources"]:
        v = v[v["แหล่ง"].isin(f["sources"])]
    if f["days"]:
        v = v[v["published_dt"] >= datetime.now(timezone.utc) - timedelta(days=f["days"])]
    if f["categories"]:
        v = v[v["หมวด"].isin(f["categories"])]
    if f["sentiments"]:
        v = v[v["น้ำเสียง"].isin(f["sentiments"])]
    if f["query"]:
        words = [w.strip().lower() for w in f["query"].split(",") if w.strip()]
        text = (v["title"].fillna("") + " " + v["summary"].fillna("") + " " + v["content"].fillna("")).str.lower()
        v = v[text.apply(lambda t: any(w in t for w in words))]
    return v


def build_view(res, f):
    """คิดตารางทั้งหมดใหม่จากข้อมูลที่กรองแล้ว (ตัวเลขทุกตัวในหน้ามาจากที่นี่)"""
    df, a, b, c = analyze.tables_from_df(apply_filters(res["df"], f))
    companies = [x for x in res["companies"] if not f["companies"] or x in f["companies"]]
    fin = res["fin"]
    if not fin.empty:
        fin = fin[fin.index.isin(companies)]
    fin_raw = {k: v for k, v in res["fin_raw"].items() if k in companies}
    reviews = analyze.review_table(df) if not df.empty else pd.DataFrame()
    self_name = res["self_name"] if res["self_name"] in companies else None
    gap = (analyze.gap_table(df, b, self_name, reviews, fin)
           if self_name and not b.empty else pd.DataFrame())
    return dict(df=df, a=a, b=b, c=c, reviews=reviews, gap=gap, fin=fin, fin_raw=fin_raw,
                companies=companies, self_name=self_name)


# ---------- ส่วนบนของหน้า ----------

def kpi_cards(v):
    df, table_b, self_name = v["df"], v["b"], v["self_name"]
    competitors = [c for c in v["companies"] if c != self_name and c in table_b.index]
    news = analyze.news_only(df)
    for start in range(0, len(v["companies"]), 4):
        names = v["companies"][start:start + 4]
        for col, name in zip(st.columns(len(names)), names):
            with col.container(border=True):
                is_self = name == self_name
                st.markdown(f"#### {name}" + ("  :blue-badge[บริษัทเรา]" if is_self else ""))
                sub = news[news["company"] == name]
                if not sub.empty and name in table_b.index:
                    pos, neg = table_b.loc[name, "positive"], table_b.loc[name, "negative"]
                    pos_delta = neg_delta = None
                    if is_self and competitors:
                        pos_delta = f"{pos - table_b.loc[competitors, 'positive'].mean():+.0f} จุด"
                        neg_delta = f"{neg - table_b.loc[competitors, 'negative'].mean():+.0f} จุด"
                    c1, c2, c3 = st.columns(3)
                    c1.metric("ข่าว", len(sub), help="จำนวนข่าว ข่าวแจ้งตลาด และบทความ (ไม่รวมรีวิว)")
                    c2.metric("บวก", f"{pos:.0f}%", pos_delta,
                              help="% ของข่าวที่เป็นผลดีต่อบริษัท ตัวเลขด้านล่างคือส่วนต่างจากค่าเฉลี่ยคู่แข่ง")
                    c3.metric("ลบ", f"{neg:.0f}%", neg_delta, delta_color="inverse",
                              help="% ของข่าวที่เป็นผลเสียต่อบริษัท ยิ่งน้อยยิ่งดี")
                    top = sub["หมวด"].value_counts()
                    st.caption(f"เน้นมากที่สุด: **{top.index[0]}** ({top.iloc[0] / len(sub) * 100:.0f}% ของข่าว)")
                else:
                    st.caption("ไม่มีข่าวตามตัวกรองนี้")
                reviews = v["reviews"]
                if not reviews.empty and name in reviews.index:
                    r = reviews.loc[name]
                    st.caption(f"รีวิวแอป ★ **{r['avg_stars']:.1f}** จาก {int(r['reviews'])} รีวิว "
                               f"(รีวิวลบ {r['negative_pct']:.0f}%)")
                fin = v["fin"]
                if not fin.empty and name in fin.index and pd.notna(fin.loc[name, "revenue_mb"]):
                    f = fin.loc[name]
                    growth = [f"{label} {f[col]:+.1f}%" for label, col in
                              (("รายได้", "revenue_yoy_pct"), ("กำไร", "net_profit_yoy_pct")) if pd.notna(f[col])]
                    st.caption(f"งบ {f['period']}: รายได้ **{f['revenue_mb']:,.0f} ลบ.**"
                               + (f" · เทียบปีก่อน {' · '.join(growth)}" if growth else ""))


def glossary():
    with st.popover("คำศัพท์", icon=":material/help:"):
        for term, text in GLOSSARY.items():
            st.markdown(f"**{term}** — {text}")


# ---------- แท็บ ----------

def tab_summary(res, v, f, active, scope, on_report):
    left, right = st.columns([3, 2], gap="large")
    with left:
        title = f"ข้อเสนอแนะสำหรับ {res['self_name']}" if res["self_name"] else "รายงานสรุป"
        st.markdown(f"##### {title}")
        report_scope = res.get("report_scope")
        st.caption(f"เขียนโดย LLM เมื่อ {fmt_time(res['report_at'])} จากตัวเลขในหน้านี้เท่านั้น · "
                   + (f"ขอบเขต: {report_scope}" if report_scope else "จากข้อมูลทั้งหมดของรอบวิเคราะห์"))
        if active and report_scope != scope:
            st.info("รายงานนี้ไม่ได้เขียนจากตัวกรองปัจจุบัน", icon=":material/info:")
            if st.button("เขียนรายงานใหม่ตามตัวกรองนี้", icon=":material/edit_note:",
                         help="ใช้ LLM 1 ครั้ง เขียนจากตัวเลขที่กรองแล้ว"):
                with friendly_errors(), st.spinner("กำลังเขียนรายงาน..."):
                    rewrite_report(res, v, scope, on_report)
                    st.rerun()
        st.markdown(res["report"])
        st.download_button("ดาวน์โหลดรายงาน (.md)", res["report"], "report.md", "text/markdown",
                           icon=":material/download:", on_click="ignore")
    with right:
        st.markdown("##### น้ำเสียงข่าว")
        if v["b"].empty:
            st.caption("ไม่มีข่าวตามตัวกรองนี้")
            return
        insights.show(st, insights.sentiment(v["b"]))
        st.altair_chart(charts.sentiment_chart(v["b"], v["self_name"]), width="stretch")
        st.caption("แต่ละแถบคือข่าวทั้งหมดของบริษัทนั้น แบ่งเป็น % ข่าวบวก/กลาง/ลบ")


def rewrite_report(res, v, scope, on_report):
    self_name = v["self_name"] if not v["gap"].empty else None
    mode = "phase1" if not self_name else ("phase3" if res["mode"] == "discover" else "phase2")
    full_scope = " · ".join(s for s in (res.get("focus_label"), scope) if s)  # หัวข้อที่สนใจ + ตัวกรอง
    analyze.write_report(v["a"], v["b"], v["c"], self_name=self_name, gap=v["gap"] if self_name else None,
                         mode=mode, reviews=v["reviews"], fin=v["fin"], scope=full_scope)
    on_report(db.latest_report(mode), scope)


def tab_gap(v):
    gap, self_name = v["gap"], v["self_name"]
    st.caption(f"{self_name} เทียบกับค่าเฉลี่ยของคู่แข่ง · “จุด” คือผลต่างของ % เช่น เรา 30% คู่แข่ง 20% = +10 จุด")
    ahead, behind = insights.gap(gap, self_name)
    c1, c2 = st.columns(2)
    with c1.container(border=True):
        st.markdown(":green[**จุดที่เรานำ**]")
        insights.show(st, ahead or ["ยังไม่พบจุดที่นำชัดเจน"])
    with c2.container(border=True):
        st.markdown(":red[**จุดที่เราตาม**]")
        insights.show(st, behind or ["ยังไม่พบจุดที่ตามชัดเจน"])
    left, right = st.columns(2, gap="large")
    with left:
        st.markdown("##### หมวดข่าว: เราเน้นต่างจากคู่แข่งตรงไหน")
        st.altair_chart(charts.gap_chart(gap, "category", self_name), width="stretch")
        st.caption("หมวดคิดเป็น % ของข่าวแต่ละบริษัท มาก/น้อยกว่าไม่ได้แปลว่าดีหรือแย่")
    with right:
        st.markdown("##### น้ำเสียงข่าว: เราดีหรือแย่กว่า")
        st.altair_chart(charts.gap_chart(gap, "sentiment", self_name), width="stretch")
    with st.expander("ตารางส่วนต่างทั้งหมด"):
        table = gap.copy()
        table["type"] = table["type"].map(GAP_TYPE_TH)
        table["item"] = table["item"].map(GAP_ITEM_TH)
        st.dataframe(
            table.rename(columns={"type": "ด้าน", "item": "รายการ", "us_pct": self_name,
                                  "competitor_avg_pct": "คู่แข่งเฉลี่ย", "gap_pts": "ส่วนต่าง"}),
            hide_index=True, width="stretch")
        st.caption("หน่วยเป็น % ยกเว้นคะแนนรีวิวเป็นดาว (1–5) · แถวการเงินเทียบเฉพาะคู่แข่งที่อยู่ในตลาดหลักทรัพย์ฯ")


def section_categories(v):
    news = analyze.news_only(v["df"])
    insights.show(st, insights.categories(news))
    st.altair_chart(charts.category_chart(news, v["self_name"]), width="stretch")
    with st.expander("จำนวนข่าวต่อหมวด"):
        st.dataframe(v["a"].rename(columns=CATEGORY_TH).rename_axis(index="บริษัท", columns=None), width="stretch")
        st.caption("แถวและคอลัมน์ “รวม” คือผลรวม")


def section_reviews(v):
    r = v["df"][v["df"]["source_type"] == "review"]
    st.caption("รีวิวล่าสุดจาก App Store และ Google Play · ดาวมาจากผู้รีวิวโดยตรง ส่วนน้ำเสียงและสรุปมาจาก LLM")
    insights.show(st, insights.reviews(v["reviews"]))
    left, right = st.columns(2, gap="large")
    with left:
        st.markdown("##### คะแนนเฉลี่ย (ดาว)")
        st.altair_chart(charts.stars_chart(r, v["self_name"]), width="stretch")
    with right:
        st.markdown("##### น้ำเสียงของรีวิว")
        sent = (pd.crosstab(r["company"], r["sentiment"], normalize="index") * 100).round(1)
        sent = sent.reindex(columns=["positive", "neutral", "negative"], fill_value=0)
        st.altair_chart(charts.sentiment_chart(sent, v["self_name"]), width="stretch")
    st.markdown("##### รีวิวล่าสุด")
    st.dataframe(
        r.sort_values("published_dt", ascending=False),
        hide_index=True, width="stretch", height=380,
        column_order=["วันที่", "company", "source_name", "rating", "น้ำเสียง", "content", "summary"],
        column_config={
            "company": st.column_config.TextColumn("บริษัท"),
            "source_name": st.column_config.TextColumn("สโตร์"),
            "rating": st.column_config.NumberColumn("ดาว", format="%d ★"),
            "content": st.column_config.TextColumn("รีวิว", width="large"),
            "summary": st.column_config.TextColumn("สรุป", width="medium"),
        },
    )


def section_finance(res, v):
    fin, raw, self_name = v["fin"], v["fin_raw"], v["self_name"]
    missing = [c for c in v["companies"] if c not in fin.index]
    fetched = max(f["fetched_at"] for f in raw.values())
    as_of = max(f["market"].get("as_of") or "" for f in raw.values())
    st.caption(f"งบรวมที่บริษัทยื่นต่อตลาดหลักทรัพย์ฯ (ดึงเมื่อ {fmt_time(fetched)}) · ราคาหุ้น ณ {as_of} · "
               "ตัวเงินหน่วยล้านบาท · ตัวกรองช่วงเวลา/หมวดไม่มีผลกับงบ"
               + (f" · ไม่มีงบ: {', '.join(missing)}" if missing else ""))
    insights.show(st, insights.finance(fin))
    left, right = st.columns(2, gap="large")
    with left:
        st.markdown("##### รายได้และกำไรสุทธิรายปี")
        chart = charts.finance_history_chart(raw, self_name)
        if chart is not None:
            st.altair_chart(chart, width="stretch")
    with right:
        st.markdown("##### เทียบงบรอบล่าสุด (%)")
        st.altair_chart(charts.finance_ratio_chart(fin, self_name), width="stretch")
        st.caption("รายได้/กำไรโต = เทียบช่วงเดียวกันปีก่อน (ถ้าปีก่อนขาดทุนจะไม่แสดง) · ROE มาจากงบทั้งปีล่าสุด")
    order = charts.company_order(list(fin.index), self_name)
    st.dataframe(
        fin.loc[order], width="stretch",
        column_config={
            "company": st.column_config.TextColumn("บริษัท"),
            "period": st.column_config.TextColumn("งบรอบ", help="6M = ครึ่งปีแรก, 9M = 9 เดือน"),
            "revenue_mb": st.column_config.NumberColumn("รายได้รวม (ลบ.)", format="localized"),
            "revenue_yoy_pct": st.column_config.NumberColumn("รายได้โต (%)", format="%+.1f",
                                                             help="เทียบช่วงเดียวกันของปีก่อน"),
            "net_profit_mb": st.column_config.NumberColumn("กำไรสุทธิ (ลบ.)", format="localized"),
            "net_profit_yoy_pct": st.column_config.NumberColumn("กำไรโต (%)", format="%+.1f"),
            "net_margin_pct": st.column_config.NumberColumn("อัตรากำไรสุทธิ (%)", format="%.1f",
                                                            help=GLOSSARY["อัตรากำไรสุทธิ"]),
            "ebitda_margin_pct": st.column_config.NumberColumn("อัตรา EBITDA (%)", format="%.1f",
                                                               help=GLOSSARY["EBITDA"]),
            "fy": st.column_config.NumberColumn("ปีงบ (ROE, D/E)", format="%d"),
            "roe_pct": st.column_config.NumberColumn("ROE (%)", format="%.1f", help=GLOSSARY["ROE"]),
            "de_ratio": st.column_config.NumberColumn("D/E (เท่า)", format="%.2f", help=GLOSSARY["D/E"]),
            "market_cap_mb": st.column_config.NumberColumn("มูลค่าตลาด (ลบ.)", format="localized"),
            "pe": st.column_config.NumberColumn("P/E (เท่า)", format="%.1f", help=GLOSSARY["P/E"]),
            "dividend_yield_pct": st.column_config.NumberColumn("ปันผล (%)", format="%.2f"),
        },
    )
    links = [f"[{f['symbol']} {f['latest']['period']}]({f['latest']['filed_url']})"
             for f in raw.values() if f["latest"].get("filed_url")]
    if links:
        st.caption("งบฉบับเต็ม (zip): " + " · ".join(links))


def tab_deep(res, v):
    sections = {}
    if not v["a"].empty:
        sections["หมวดข่าว"] = lambda: section_categories(v)
    if not v["reviews"].empty:
        sections["รีวิวแอป"] = lambda: section_reviews(v)
    if not v["fin"].empty:
        sections["งบการเงิน"] = lambda: section_finance(res, v)
    if not sections:
        st.caption("ไม่มีข้อมูลตามตัวกรองนี้")
        return
    pick = st.segmented_control("ดูเรื่อง", list(sections), key="deep_pick", default=list(sections)[0],
                                label_visibility="collapsed")
    sections.get(pick or list(sections)[0], sections[list(sections)[0]])()


def tab_data(v):
    df = v["df"]
    st.caption(f"{len(df)} รายการ เรียงจากใหม่ไปเก่า · กรองด้วยแถบด้านบน")
    st.dataframe(
        df.sort_values("published_dt", ascending=False),
        hide_index=True, width="stretch", height=520,
        column_order=["วันที่", "company", "แหล่ง", "source_name", "หมวด", "น้ำเสียง", "title", "summary", "url"],
        column_config={
            "company": st.column_config.TextColumn("บริษัท"),
            "source_name": st.column_config.TextColumn("ที่มา"),
            "title": st.column_config.TextColumn("หัวข้อ", width="large"),
            "summary": st.column_config.TextColumn("สรุป", width="large"),
            "url": st.column_config.LinkColumn("ลิงก์", display_text="เปิด"),
        },
    )
    csv = (df[["วันที่", "company", "แหล่ง", "source_name", "หมวด", "น้ำเสียง", "rating", "title", "summary", "url"]]
           .rename(columns={"company": "บริษัท", "source_name": "ที่มา", "rating": "ดาว",
                            "title": "หัวข้อ", "summary": "สรุป", "url": "ลิงก์"})
           .to_csv(index=False).encode("utf-8-sig"))  # BOM ให้ Excel อ่านไทยได้
    st.download_button("ดาวน์โหลดข้อมูลที่กรองแล้ว (.csv)", csv, "data.csv", "text/csv",
                       icon=":material/table:", on_click="ignore")


# ---------- ประกอบหน้า ----------

def show(res, on_report):
    head, gloss = st.columns([6, 1], vertical_alignment="center")
    counts = res["df"]["แหล่ง"].value_counts()
    head.caption(f"{' · '.join(res['companies'])} · "
                 + " · ".join(f"{label} {n}" for label, n in counts.items())
                 + f" · อัปเดตล่าสุด {fmt_time(res['fetched_at'])}")
    if res.get("focus_label"):
        head.caption(f"วิเคราะห์เฉพาะเรื่อง: **{res['focus_label']}**")
    with gloss:
        glossary()

    f = filter_bar(res)
    scope = describe(f)
    active = bool(scope)
    v = build_view(res, f)
    if active:
        st.caption(f"กำลังกรอง: {scope} · เหลือ {len(v['df'])} จาก {len(res['df'])} รายการ")
    if v["df"].empty and v["fin"].empty:
        st.warning("ไม่มีข้อมูลตามตัวกรองนี้ ลองขยายช่วงเวลาหรือกด “ล้าง”")
        return

    kpi_cards(v)
    has_gap = bool(v["self_name"]) and not v["gap"].empty
    names = ["สรุป"] + (["เรา vs คู่แข่ง"] if has_gap else []) + ["เจาะลึก", "ข้อมูลทั้งหมด"]
    renders = ([lambda: tab_summary(res, v, f, active, scope, on_report)]
               + ([lambda: tab_gap(v)] if has_gap else [])
               + [lambda: tab_deep(res, v), lambda: tab_data(v)])
    for tab, render in zip(st.tabs(names), renders):
        with tab:
            render()
