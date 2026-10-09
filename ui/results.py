"""หน้าผลลัพธ์: แถบตัวกรอง (กรองทุกกราฟ/ตาราง) → การ์ดสรุปต่อบริษัท → 4 แท็บ"""
from datetime import datetime, timedelta, timezone

import pandas as pd
import streamlit as st

from core import analyze, ask, benchmark, collect, db, export, impact
from ui import charts, insights
from ui.common import ago, fmt_time, friendly_errors
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
    groups = {m: g for m, g in res.get("groups", {}).items() if m in companies}
    internal = analyze.internal_table(companies)
    gap = (analyze.gap_table(df, b, self_name, reviews, fin, members=groups, internal=internal)
           if self_name and not b.empty else pd.DataFrame())
    return dict(df=df, a=a, b=b, c=c, reviews=reviews, gap=gap, fin=fin, fin_raw=fin_raw,
                companies=companies, self_name=self_name, groups=groups, internal=internal)


# ---------- ส่วนบนของหน้า ----------

def kpi_cards(v):
    df, table_b, self_name = v["df"], v["b"], v["self_name"]
    groups = v["groups"]
    competitors = [c for c in v["companies"] if c != self_name and c in table_b.index and c not in groups]
    news = analyze.news_only(df)
    for start in range(0, len(v["companies"]), 4):
        names = v["companies"][start:start + 4]
        for col, name in zip(st.columns(len(names)), names):
            with col.container(border=True):
                is_self = name == self_name
                parent = groups.get(name, {}).get("parent")
                st.markdown(f"#### {name}" + ("  :blue-badge[บริษัทเรา]" if is_self else "")
                            + (f"  :gray-badge[ในเครือ {parent}]" if parent else ""))
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


CHANGE_ICON = {"set": "📢", "negative": "⚠️", "financials": "💰", "sentiment": "📉", "reviews": "⭐",
               "promotion": "🏷️", "volume": "🆕", "price_move": "📈"}


def changes_box(res):
    """สิ่งที่เปลี่ยนไปตั้งแต่รอบก่อน (คิดจากข้อมูลโดยระบบ ไม่ใช่ LLM)"""
    changes = res.get("changes")
    if changes is None:
        return
    if not changes:
        st.caption(":material/history: เทียบกับรอบก่อน: ไม่มีอะไรเปลี่ยน หรือเป็นรอบแรกของบริษัทเหล่านี้")
        return

    def line(c):
        out = f"{CHANGE_ICON.get(c['kind'], '•')} **{c['company']}** {c['text']}"
        items = "".join(f"\n    - [{it['title']}]({it['url']})" if it["url"] else f"\n    - {it['title']}"
                        for it in c["items"][:3])
        return "- " + out + items

    high = [c for c in changes if c["level"] == "high"]
    info = [c for c in changes if c["level"] != "high"]
    with st.container(border=True):
        st.markdown("##### อะไรเปลี่ยนไปตั้งแต่รอบก่อน" + (f"  :red-badge[สำคัญ {len(high)}]" if high else ""))
        st.caption(f"รอบนี้เสร็จเมื่อ {fmt_time(res.get('run_at'))} · เทียบกับรอบล่าสุดก่อนหน้าของแต่ละบริษัท")
        if high:
            st.markdown("\n".join(line(c) for c in high))
        if info:
            with st.expander(f"เรื่องอื่น ๆ ({len(info)})", expanded=not high):
                st.markdown("\n".join(line(c) for c in info))


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
        title = (f"{res['self_name']} vs " + ", ".join(c for c in res["companies"] if c != res["self_name"])
                 if res["self_name"] else " · ".join(res["companies"]))
        d1, d2 = st.columns(2)
        d1.download_button("ดาวน์โหลด Word (.docx)",
                           export.report_docx(res["report"], f"Competitor Compare: {title}",
                                              f"เขียนเมื่อ {fmt_time(res['report_at'])} · ทุกตัวเลขมาจากข้อมูลที่ระบบดึงมา "
                                              "ลิงก์ [n] เปิดแหล่งที่มาได้"),
                           f"report_{res['report_id']}.docx",
                           "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                           icon=":material/description:", on_click="ignore", width="stretch")
        d2.download_button("Markdown (.md)", res["report"], "report.md", "text/markdown",
                           icon=":material/download:", on_click="ignore", width="stretch")
    with right:
        st.markdown("##### น้ำเสียงข่าว")
        if v["b"].empty:
            st.caption("ไม่มีข่าวตามตัวกรองนี้")
            return
        insights.show(st, insights.sentiment(v["b"]))
        st.altair_chart(charts.sentiment_chart(v["b"], v["self_name"]), width="stretch")
        st.caption("แต่ละแถบคือข่าวทั้งหมดของบริษัทนั้น แบ่งเป็น % ข่าวบวก/กลาง/ลบ")


def market_tables(v):
    """อันดับในหมวดและราคาหุ้นหลังข่าว (ตามตัวกรอง) สำหรับส่งให้รายงาน/คำถาม"""
    companies = benchmark.symbols_of(v["companies"])
    if not companies:
        return {"sector": None, "price": None}
    return {"sector": benchmark.table(companies), "price": impact.events(v["df"], companies)}


def key_points(res, v):
    """สิ่งที่ควรรู้: 3–5 ข้อสำคัญจากทุกส่วน คิดจากข้อมูลโดยระบบ (ไม่ใช่ LLM) แต่ละข้อมีที่มา"""
    points = []
    high = [c for c in (res.get("changes") or []) if c["level"] == "high"]
    if high:
        points.append(f"ตั้งแต่รอบก่อนมี **{len(high)} เรื่องสำคัญ** เช่น "
                      + "; ".join(f"{c['company']} {c['text']}" for c in high[:2]))
    m = market_tables(v)
    if m["sector"] is not None and not m["sector"].empty:
        me = v["self_name"]
        tb = m["sector"][m["sector"]["company"] == me] if me in set(m["sector"]["company"]) else m["sector"]
        points += benchmark.highlights(tb)[:1 if me else 2]
    if m["price"] is not None and not m["price"].empty:
        for _, r in m["price"][m["price"]["big"]].head(2).iterrows():
            title = r["titles"][0][:70]
            link = f"[{title}]({r['urls'][0]})" if r["urls"] and r["urls"][0] else title
            points.append(f"**{r['company']}** หุ้นขยับ {impact.describe(r)} หลังข่าว {r['date']}: {link}")
    gap = v["gap"]
    if not gap.empty:
        g = gap[gap["type"].isin(["sentiment", "finance", "review"])]
        if not g.empty:
            r = g.loc[g["gap_pts"].abs().idxmax()]
            label = GAP_ITEM_TH.get(r["item"], r["item"]).split(" (")[0]
            points.append(f"**{v['self_name']}** ต่างจากคู่แข่งมากที่สุดเรื่อง {label}: "
                          f"{r['us_pct']:g} เทียบค่าเฉลี่ยคู่แข่ง {r['competitor_avg_pct']:g} ({r['gap_pts']:+g} จุด)")
    if not points:
        return
    with st.container(border=True):
        st.markdown("##### สิ่งที่ควรรู้")
        st.markdown("\n".join(f"- {p}" for p in points[:5]))
        st.caption("คิดจากข้อมูลโดยระบบ ไม่ใช่ LLM · รายละเอียดอยู่ในแท็บด้านล่าง")


def rewrite_report(res, v, scope, on_report):
    self_name = v["self_name"] if not v["gap"].empty else None
    mode = "phase1" if not self_name else ("phase3" if res["mode"] == "discover" else "phase2")
    full_scope = " · ".join(s for s in (res.get("focus_label"), scope) if s)  # หัวข้อที่สนใจ + ตัวกรอง
    analyze.write_report(v["a"], v["b"], v["c"], self_name=self_name, gap=v["gap"] if self_name else None,
                         mode=mode, reviews=v["reviews"], fin=v["fin"], scope=full_scope, groups=v["groups"],
                         changes=res.get("changes"),
                         internal=v["internal"] if st.session_state.get("internal_llm", True) else None,
                         **market_tables(v))
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
        table["item"] = table["item"].map(lambda i: GAP_ITEM_TH.get(i, i))
        st.dataframe(
            table.rename(columns={"type": "ด้าน", "item": "รายการ", "us_pct": self_name,
                                  "competitor_avg_pct": "คู่แข่งเฉลี่ย", "gap_pts": "ส่วนต่าง"}),
            hide_index=True, width="stretch")
        st.caption("หน่วยเป็น % ยกเว้นคะแนนรีวิวเป็นดาว (1–5) และข้อมูลภายในใช้หน่วยตามไฟล์ที่อัปโหลด · "
                   "แถวการเงินเทียบเฉพาะคู่แข่งที่อยู่ในตลาดหลักทรัพย์ฯ")


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


BANK_COLUMNS = ("nii_mb", "nii_yoy_pct", "fee_income_mb", "fee_income_yoy_pct", "nim_approx_pct",
                "cost_to_income_pct", "credit_cost_pct", "ldr_pct", "loans_mb", "deposits_mb")


def section_banks(banks, self_name):
    st.markdown("##### ตัวชี้วัดธนาคาร")
    st.caption("คิดจากงบย่อที่ยื่น SET · ตัวเลขต่อปีแปลงจากงบสะสม (เช่น 6 เดือน × 2) · "
               "ไม่มี NPL เพราะงบย่อของ SET ไม่มีข้อมูลนี้")
    st.altair_chart(charts.bank_ratio_chart(banks, self_name), width="stretch")
    st.dataframe(
        banks, width="stretch",
        column_config={
            "company": st.column_config.TextColumn("บริษัท"),
            "nii_mb": st.column_config.NumberColumn("รายได้ดอกเบี้ยสุทธิ (ลบ.)", format="localized"),
            "nii_yoy_pct": st.column_config.NumberColumn("ดอกเบี้ยสุทธิโต (%)", format="%+.1f"),
            "fee_income_mb": st.column_config.NumberColumn("ค่าธรรมเนียมสุทธิ (ลบ.)", format="localized"),
            "fee_income_yoy_pct": st.column_config.NumberColumn("ค่าธรรมเนียมโต (%)", format="%+.1f"),
            "nim_approx_pct": st.column_config.NumberColumn("NIM โดยประมาณ (%)", format="%.2f",
                                                            help=GLOSSARY["NIM โดยประมาณ"]),
            "cost_to_income_pct": st.column_config.NumberColumn("Cost to income (%)", format="%.1f",
                                                                help=GLOSSARY["Cost to income"]),
            "credit_cost_pct": st.column_config.NumberColumn("Credit cost (%)", format="%.2f",
                                                             help=GLOSSARY["Credit cost"]),
            "ldr_pct": st.column_config.NumberColumn("สินเชื่อ/เงินฝาก (%)", format="%.1f",
                                                     help=GLOSSARY["สินเชื่อ/เงินฝาก (LDR)"]),
            "loans_mb": st.column_config.NumberColumn("สินเชื่อสุทธิ (ลบ.)", format="localized"),
            "deposits_mb": st.column_config.NumberColumn("เงินฝาก (ลบ.)", format="localized"),
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
    bank_cols = [c for c in BANK_COLUMNS if c in fin.columns]
    st.dataframe(
        fin.loc[order].drop(columns=bank_cols), width="stretch",
        column_config={
            "company": st.column_config.TextColumn("บริษัท"),
            "symbol": st.column_config.TextColumn("ชื่อหุ้น"),
            "sector": st.column_config.TextColumn("หมวดธุรกิจ (SET)"),
            "period": st.column_config.TextColumn("งบรอบ", help="6M = ครึ่งปีแรก, 9M = 9 เดือน"),
            "revenue_mb": st.column_config.NumberColumn("รายได้รวม (ลบ.)", format="localized",
                                                        help="ธนาคารใช้รายได้จากการดำเนินงาน "
                                                             "(ดอกเบี้ยสุทธิ + ค่าธรรมเนียมสุทธิ + อื่น ๆ)"),
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
    banks = fin.loc[order, bank_cols].dropna(how="all") if bank_cols else pd.DataFrame()
    if not banks.empty:
        section_banks(banks, self_name)
    links =[f"[{f['symbol']} {f['latest']['period']}]({f['latest']['filed_url']})"
             for f in raw.values() if f["latest"].get("filed_url")]
    if links:
        st.caption("งบฉบับเต็ม (zip): " + " · ".join(links))


def section_trends(v):
    news = analyze.news_only(v["df"])
    st.caption("นับตามวันที่เผยแพร่ รายสัปดาห์ · ข้อมูลย้อนหลังจะยาวขึ้นเรื่อย ๆ เมื่อรันอัตโนมัติทุกวัน "
               "(แต่ละรอบดึงได้เฉพาะข่าวล่าสุดของแต่ละแหล่ง)")
    left, right = st.columns(2, gap="large")
    with left:
        st.markdown("##### จำนวนข่าวต่อสัปดาห์")
        st.altair_chart(charts.weekly_volume_chart(news, v["self_name"]), width="stretch")
    with right:
        st.markdown("##### ข่าวลบต่อสัปดาห์ (%)")
        st.altair_chart(charts.weekly_negative_chart(news, v["self_name"]), width="stretch")
        st.caption("แสดงเฉพาะสัปดาห์ที่มีข่าวอย่างน้อย 3 ข่าว")
    reviews = v["df"][v["df"]["source_type"] == "review"]
    if reviews["rating"].notna().sum() >= 5:
        st.markdown("##### คะแนนรีวิวเฉลี่ยต่อสัปดาห์")
        st.altair_chart(charts.weekly_stars_chart(reviews, v["self_name"]), width="stretch")


def section_internal(v):
    table, units = v["internal"], v["internal"].attrs.get("units", {})
    st.caption("ตัวเลขจากไฟล์ที่อัปโหลด (ไม่ได้มาจากแหล่งสาธารณะ) · แก้หรือเพิ่มได้ใน “ข้อมูลภายในบริษัท” ด้านบน")
    metrics = list(table.columns)
    pick = st.selectbox("ตัวชี้วัด", metrics, key="internal_pick") if len(metrics) > 1 else metrics[0]
    u = units.get(pick, {})
    st.altair_chart(charts.internal_chart(table, pick, v["self_name"], u.get("unit", "")), width="stretch")
    st.dataframe(table.rename(columns=lambda m: f"{m} ({units.get(m, {}).get('unit')})"
                              if units.get(m, {}).get("unit") else m),
                 width="stretch")
    periods = {m: x["period"] for m, x in units.items() if x.get("period")}
    if periods:
        st.caption("ช่วงเวลา: " + " · ".join(f"{m} {p}" for m, p in periods.items()))


def section_sector(v):
    companies = benchmark.symbols_of(v["companies"])
    symbols = list(dict.fromkeys(companies.values()))
    fr = benchmark.frames(symbols)
    missing = [s for s in symbols if s not in fr]
    if missing and st.button(f"ดึงตัวเลขทุกบริษัทในหมวดของ {', '.join(missing)} จาก SET",
                             icon=":material/download:", key="bench_fetch",
                             help="ไม่ใช้ LLM · ประมาณ 1 วินาทีต่อ 4 บริษัท · เก็บไว้ใช้ซ้ำ 1 วัน"):
        with friendly_errors(), st.spinner("กำลังดึงตัวเลขทุกบริษัทในหมวด..."):
            benchmark.refresh(missing, log=st.caption)
        st.rerun()
    if not fr:
        st.caption("ยังไม่มีตัวเลขของหมวดธุรกิจ กดปุ่มด้านบนเพื่อดึงจาก SET")
        return
    tb = benchmark.table(companies)
    st.caption("เทียบกับทุกบริษัทจดทะเบียนในหมวดธุรกิจเดียวกันของ SET (ไม่ใช่แค่คู่แข่งที่เลือก) · "
               "ใช้งบทั้งปีล่าสุดของแต่ละบริษัท บริษัทที่ปีบัญชีจบกลางปีจะเป็นปีงบที่ต่างกัน · ไม่ผ่าน LLM")
    insights.show(st, benchmark.highlights(tb))
    by_group = {}
    for name, sym in companies.items():
        if sym in fr:
            by_group.setdefault(fr[sym]["group"], []).append((name, sym))
    labels = {g: f"{fr[members[0][1]]['name']} · {len(fr[members[0][1]]['df'])} บริษัท"
              for g, members in by_group.items()}
    group = (st.segmented_control("หมวด", list(by_group), format_func=labels.get, key="bench_group",
                                  default=list(by_group)[0], label_visibility="collapsed")
             if len(by_group) > 1 else list(by_group)[0]) or list(by_group)[0]
    members = by_group[group]
    df = fr[members[0][1]]["df"]
    st.markdown(f"##### {labels[group]}")
    st.altair_chart(charts.sector_strip_chart(df, benchmark.percentiles(df),
                                              {sym: name for name, sym in members}, benchmark.METRIC_TH),
                    width="stretch")
    rows = tb[tb["symbol"].isin([sym for _, sym in members])]
    if not rows.empty:
        cell = rows.assign(ค่า=rows.apply(lambda r: f"{r['value']:,.2f}  (อันดับ {r['rank']}/{r['n']})", axis=1))
        pivot = cell.pivot(index="company", columns="metric", values="ค่า")
        median = rows.drop_duplicates("metric").set_index("metric")["median"].map(lambda x: f"{x:,.2f}")
        pivot.loc["มัธยฐานของหมวด"] = median
        cols = [m for m in benchmark.METRICS if m in pivot.columns]
        st.dataframe(pivot[cols].rename(columns=benchmark.METRIC_TH), width="stretch")
    as_of = df["as_of"].dropna().max() if "as_of" in df else ""
    st.caption(f"ราคาหุ้น ณ {as_of} · อันดับ 1 = ดีที่สุด (D/E ต่ำสุด, P/E ต่ำสุด = ราคาถูกเมื่อเทียบกำไร) · "
               "บริษัทที่ไม่มีตัวเลข (เช่น ขาดทุนจึงไม่มี P/E) ไม่ถูกนับ")


def section_price(v):
    companies = benchmark.symbols_of(v["companies"])
    px = impact.prices(set(companies.values()))
    missing = sorted(set(companies.values()) - set(px))
    if missing and st.button(f"ดึงราคาหุ้น 6 เดือนของ {', '.join(missing)} จาก SET", icon=":material/download:",
                             key="px_fetch", help="ไม่ใช้ LLM · 1 call ต่อหุ้น"):
        with friendly_errors(), st.spinner("กำลังดึงราคาหุ้น..."):
            impact.refresh(missing, log=st.caption)
        st.rerun()
    ev = impact.events(v["df"], companies)
    if not px or ev.empty:
        st.caption("ยังไม่มีราคาหุ้นหรือข่าวในช่วงที่มีราคา")
        return
    st.caption("วันที่มีข่าวหรือประกาศ SET แล้วหุ้นขยับเท่าไรใน 1 และ 3 วันทำการ เทียบราคาปิดก่อนข่าว "
               "และหักผลของตลาดรวม (ดัชนี SET หรือ mai ช่วงเดียวกัน) · "
               f"“ผิดปกติ” = ส่วนที่หักตลาดแล้วเกิน {impact.Z_LIMIT:.0f} เท่าของความผันผวนปกติของหุ้นตัวนั้น · "
               "ข่าวหลัง 16:30 นับเป็นวันทำการถัดไป · ยังไม่หักวันขึ้นเครื่องหมาย XD · ไม่ผ่าน LLM")
    big = ev[ev["big"]]
    lines = []
    for _, r in big.head(3).iterrows():
        link = f"[{r['titles'][0][:80]}]({r['urls'][0]})" if r["urls"] and r["urls"][0] else r["titles"][0][:80]
        lines.append(f"**{r['company']}** {r['date']}: {impact.describe(r)} หลัง {link}")
    insights.show(st, lines or ["ไม่มีวันไหนที่หุ้นขยับผิดปกติหลังข่าวในช่วงนี้"])
    names = [n for n in v["companies"] if n in companies and companies[n] in px]
    pick = st.segmented_control("บริษัท", names, key="px_pick", default=names[0],
                                label_visibility="collapsed") or names[0]
    st.altair_chart(charts.price_news_chart(px[companies[pick]], ev[ev["company"] == pick]), width="stretch")
    st.markdown("##### วันที่หุ้นขยับมากที่สุดหลังข่าว")
    table = ev.head(15).assign(หัวข้อ=ev["titles"].map(lambda t: " / ".join(t[:2])),
                               ลิงก์=ev["urls"].map(lambda u: u[0] if u else None),
                               น้ำเสียง=ev["sentiment"].map(SENTIMENT_TH))
    st.dataframe(
        table, hide_index=True, width="stretch",
        column_order=["company", "date", "r1_pct", "r3_pct", "market_r3_pct", "ar3_pct", "z", "big", "news",
                      "น้ำเสียง", "หัวข้อ", "ลิงก์"],
        column_config={
            "company": st.column_config.TextColumn("บริษัท"),
            "date": st.column_config.TextColumn("วันทำการ"),
            "r1_pct": st.column_config.NumberColumn("1 วัน (%)", format="%+.2f"),
            "r3_pct": st.column_config.NumberColumn("3 วัน (%)", format="%+.2f"),
            "market_r3_pct": st.column_config.NumberColumn("ตลาด 3 วัน (%)", format="%+.2f",
                                                           help="ดัชนี SET (หรือ mai) ช่วงเดียวกัน"),
            "ar3_pct": st.column_config.NumberColumn("หักตลาดแล้ว (%)", format="%+.2f",
                                                     help="3 วันของหุ้น − 3 วันของตลาด"),
            "z": st.column_config.NumberColumn("เท่าของปกติ", format="%+.1f",
                                               help="ผลตอบแทน ÷ ความผันผวนรายวันปกติของหุ้น (ติดลบ = ลง)"),
            "big": st.column_config.CheckboxColumn("ผิดปกติ"),
            "news": st.column_config.NumberColumn("ข่าว"),
            "หัวข้อ": st.column_config.TextColumn(width="large"),
            "ลิงก์": st.column_config.LinkColumn(display_text="เปิด"),
        })


def tab_deep(res, v):
    sections = {}
    if not v["a"].empty:
        sections["หมวดข่าว"] = lambda: section_categories(v)
    if not v["df"].empty and charts.week_start(analyze.news_only(v["df"])["published_dt"].dropna()).nunique() >= 2:
        sections["แนวโน้ม"] = lambda: section_trends(v)
    if not v["reviews"].empty:
        sections["รีวิวแอป"] = lambda: section_reviews(v)
    if not v["fin"].empty:
        sections["งบการเงิน"] = lambda: section_finance(res, v)
    if benchmark.symbols_of(v["companies"]):
        sections["เทียบทั้งหมวด"] = lambda: section_sector(v)
        sections["ราคาหุ้นหลังข่าว"] = lambda: section_price(v)
    if not v["internal"].empty:
        sections["ข้อมูลภายใน"] = lambda: section_internal(v)
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


def _examples(res):
    first = res["self_name"] or res["companies"][0]
    out = [f"{first} เปิดตัวสินค้าหรือแคมเปญอะไรบ้าง", "ใครมีโปรโมชันหรือสินค้าใหม่ใน 30 วันล่าสุด"]
    if benchmark.symbols_of(res["companies"]):
        out += ["หุ้นตัวไหนขยับแรงหลังข่าว เป็นข่าวอะไร", f"อัตรากำไรของ {first} อยู่อันดับไหนในหมวด"]
    return out


def _ask_later(question):
    st.session_state.ask_pending = question


def tab_ask(res):
    st.caption("ตอบจากข้อมูลที่ระบบเก็บไว้ของบริษัทในผลนี้เท่านั้น (ข่าว ประกาศ SET รีวิว งบ อันดับในหมวด ราคาหุ้น) "
               "ไม่ใช้ความรู้ของ LLM · ทุกข้อมีลิงก์ที่มา · ไม่มีข้อมูลจะตอบว่าไม่มี · ใช้ LLM 2 ครั้งต่อคำถาม")
    key = f"ask_history_{res.get('report_id')}"
    history = st.session_state.setdefault(key, [])
    cols = st.columns(len(_examples(res)))
    for i, (col, q) in enumerate(zip(cols, _examples(res))):
        col.button(q, key=f"ask_ex_{i}", on_click=_ask_later, args=(q,), width="stretch")
    question = st.chat_input("ถามเกี่ยวกับคู่แข่ง เช่น “AP เปิดโครงการใหม่อะไรบ้าง”", key="ask_input")
    question = question or st.session_state.pop("ask_pending", None)
    if question:
        companies = benchmark.symbols_of(res["companies"])
        with friendly_errors(), st.spinner("กำลังค้นข้อมูลที่เก็บไว้และเขียนคำตอบ..."):
            out = ask.answer(question, res["df"], res["companies"], fin=res["fin"],
                             sector=benchmark.table(companies) if companies else None,
                             price=impact.events(res["df"], companies) if companies else None)
            history.insert(0, {"q": question, **out})
    for h in history:
        with st.chat_message("user"):
            st.markdown(h["q"])
        with st.chat_message("assistant"):
            st.markdown(h["answer"])
            f = h["filters"]
            scope = [", ".join(f["companies"]) or "ทุกบริษัท"]
            if f.get("sentiments"):
                scope.append("ข่าว" + "/".join(SENTIMENT_TH[x] for x in f["sentiments"]))
            if f["keywords"]:
                scope.append("คำค้น " + ", ".join(f["keywords"]))
            if f["days"]:
                scope.append(f"{f['days']} วันล่าสุด")
            st.caption(f"ใช้ {h['used']} รายการ · ค้นจาก: {' · '.join(scope)}"
                       + (" · รวมตัวเลขงบ/อันดับ/ราคาหุ้น" if f["needs_numbers"] else "")
                       + f" · LLM {h['llm_calls']} ครั้ง")


# ---------- ประกอบหน้า ----------

def show(res, on_report):
    head, gloss = st.columns([6, 1], vertical_alignment="center")
    fresh = []  # จำนวนต่อแหล่ง + ดึงล่าสุดเมื่อไร
    if not res["df"].empty:
        by_source = res["df"].groupby("แหล่ง")["fetched_at"].agg(["size", "max"])
        fresh = [f"{label} {row['size']} (ดึง {ago(row['max'])})" for label, row in by_source.iterrows()]
    if res["fin_raw"]:
        fresh.append(f"งบ SET {len(res['fin_raw'])} บริษัท "
                     f"(ดึง {ago(max(f['fetched_at'] for f in res['fin_raw'].values()))})")
    cost = res.get("llm")
    if cost:
        fresh.append(f"รอบนี้ใช้ LLM {cost['calls']} ครั้ง ({cost['seconds']:.0f} วินาที)")
    head.caption(f"{' · '.join(res['companies'])} · " + " · ".join(fresh))
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
    if v["df"].empty and v["fin"].empty and v["internal"].empty:
        st.warning("ไม่มีข้อมูลตามตัวกรองนี้ ลองขยายช่วงเวลาหรือกด “ล้าง”")
        return

    key_points(res, v)
    changes_box(res)
    kpi_cards(v)
    has_gap = bool(v["self_name"]) and not v["gap"].empty
    names = ["สรุป"] + (["เรา vs คู่แข่ง"] if has_gap else []) + ["เจาะลึก", "ถามข้อมูล", "ข้อมูลทั้งหมด"]
    renders = ([lambda: tab_summary(res, v, f, active, scope, on_report)]
               + ([lambda: tab_gap(v)] if has_gap else [])
               + [lambda: tab_deep(res, v), lambda: tab_ask(res), lambda: tab_data(v)])
    for tab, render in zip(st.tabs(names), renders):
        with tab:
            render()
