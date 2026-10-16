"""หน้าผลลัพธ์ (อยู่ในหน้าภาพรวม): หัวผล + ปุ่ม (ตัวกรอง ติดตาม ดาวน์โหลด วิเคราะห์ใหม่) → สิ่งที่ควรรู้
→ การ์ดสรุปต่อบริษัท → แท็บ สรุป / เรา vs คู่แข่ง / เจาะลึก / ข้อมูลทั้งหมด
ลำดับตามหลัก overview first: สรุปก่อน ตัวกรองและรายละเอียดเปิดเมื่อต้องการ · ส่วนย่อยของแท็บเจาะลึกอยู่ใน ui/sections/"""
from datetime import datetime, timedelta, timezone

import pandas as pd
import streamlit as st

from core import analyze, benchmark, collect, db, export, impact
from ui import charts, insights, nav, watch_panel
from ui.sections import finance, market, news
from ui.sections.market import market_tables
from ui.common import ago, fmt_time, friendly_errors
from ui.labels import CATEGORY_TH, GAP_ITEM_TH, GAP_TYPE_TH, GLOSSARY, SENTIMENT_COLORS

PERIODS = {"7 วัน": 7, "30 วัน": 30, "90 วัน": 90, "ทั้งหมด": None}
FILTER_KEYS = ("flt_company", "flt_src", "flt_days", "flt_cat", "flt_sent", "flt_q")


def reset_filters():
    for k in FILTER_KEYS:
        st.session_state.pop(k, None)


# ---------- ตัวกรอง ----------

def active_filters():
    """จำนวนตัวกรองที่ใช้อยู่ (ใช้ตั้งชื่อปุ่มก่อนสร้าง widget)"""
    ss = st.session_state
    return sum(bool(ss.get(k)) for k in ("flt_company", "flt_src", "flt_cat", "flt_sent", "flt_q")) + (
        ss.get("flt_days") not in (None, "ทั้งหมด"))


def filter_bar(res):
    """ตัวกรองอยู่ใน popover ข้างหัวผล (เปิดเมื่อต้องการ) กรองทุกกราฟ/ตารางในหน้า"""
    df = res["df"]
    n = active_filters()
    with st.popover(f"ตัวกรอง ({n})" if n else "ตัวกรอง", icon=":material/filter_alt:", width="stretch"):
        companies = st.multiselect("บริษัท", res["companies"], key="flt_company", placeholder="ทุกบริษัท")
        sources = st.multiselect("แหล่ง", [v for v in collect.SOURCE_TYPE_LABEL.values() if v in set(df["แหล่ง"])],
                                 key="flt_src", placeholder="ทุกแหล่ง")
        period = st.segmented_control("ช่วงเวลา", list(PERIODS), key="flt_days", default="ทั้งหมด")
        cats = st.pills("หมวด", [v for v in CATEGORY_TH.values() if v in set(df["หมวด"])],
                        selection_mode="multi", key="flt_cat")
        sents = st.pills("น้ำเสียง", list(SENTIMENT_COLORS), selection_mode="multi", key="flt_sent")
        query = st.text_input("ค้นหาคำ", key="flt_q", placeholder="เช่น 5G, กำไร")
        st.button("ล้างตัวกรอง", icon=":material/filter_alt_off:", on_click=reset_filters, width="stretch",
                  key="flt_clear_pop")
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
    st.html("<style>[data-testid='stMetricValue'] {font-size: 1.7rem;} "  # ตัวเลขใหญ่เกินจนถูกตัดเป็น “…” ในการ์ดแคบ
            "[data-testid='stMetricValue'] * {overflow: visible; text-overflow: clip;}</style>")
    for start in range(0, len(v["companies"]), 3):  # 3 การ์ดต่อแถว (4 ใบทำให้แคบเกินไป)
        names = v["companies"][start:start + 3]
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
    with st.popover("คำศัพท์", icon=":material/help:", width="stretch"):
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
        nav.link("ask", "ถามเพิ่มเกี่ยวกับผลนี้", icon=":material/forum:")
    with right:
        st.markdown("##### น้ำเสียงข่าว")
        if v["b"].empty:
            st.caption("ไม่มีข่าวตามตัวกรองนี้")
            return
        insights.show(st, insights.sentiment(v["b"]))
        st.altair_chart(charts.sentiment_chart(v["b"], v["self_name"]), width="stretch")
        st.caption("แต่ละแถบคือข่าวทั้งหมดของบริษัทนั้น แบ่งเป็น % ข่าวบวก/กลาง/ลบ")


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


def highlights(res, v):
    """สิ่งที่ควรรู้ + อะไรเปลี่ยนไป วางคู่กัน (มีอย่างเดียวก็เต็มความกว้าง)"""
    if res.get("changes"):
        left, right = st.columns(2, gap="medium")
        with left:
            key_points(res, v)
        with right:
            changes_box(res)
    else:
        key_points(res, v)
        changes_box(res)


def rewrite_report(res, v, scope, on_report):
    self_name = v["self_name"] if not v["gap"].empty else None
    mode = "phase1" if not self_name else ("phase3" if res["mode"] == "discover" else "phase2")
    full_scope = " · ".join(s for s in (res.get("focus_label"), scope) if s)  # หัวข้อที่สนใจ + ตัวกรอง
    analyze.write_report(v["a"], v["b"], v["c"], self_name=self_name, gap=v["gap"] if self_name else None,
                         mode=mode, reviews=v["reviews"], fin=v["fin"], scope=full_scope, groups=v["groups"],
                         changes=res.get("changes"),
                         internal=v["internal"] if st.session_state.get("internal_llm_on", True) else None,
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


def tab_deep(res, v):
    sections = {}
    if not v["a"].empty:
        sections["หมวดข่าว"] = lambda: news.section_categories(v)
    if not v["df"].empty and charts.week_start(analyze.news_only(v["df"])["published_dt"].dropna()).nunique() >= 2:
        sections["แนวโน้ม"] = lambda: news.section_trends(v)
    if not v["reviews"].empty:
        sections["รีวิวแอป"] = lambda: news.section_reviews(v)
    if not v["fin"].empty:
        sections["งบการเงิน"] = lambda: finance.section_finance(res, v)
    if benchmark.symbols_of(v["companies"]):
        sections["เทียบทั้งหมวด"] = lambda: market.section_sector(v)
        sections["ราคาหุ้นหลังข่าว"] = lambda: market.section_price(v)
    if not v["internal"].empty:
        sections["ข้อมูลภายใน"] = lambda: news.section_internal(v)
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


# ---------- ประกอบหน้า ----------

def _csv(df):
    return (df[["วันที่", "company", "แหล่ง", "source_name", "หมวด", "น้ำเสียง", "rating", "title", "summary", "url"]]
            .rename(columns={"company": "บริษัท", "source_name": "ที่มา", "rating": "ดาว",
                             "title": "หัวข้อ", "summary": "สรุป", "url": "ลิงก์"})
            .to_csv(index=False).encode("utf-8-sig"))  # BOM ให้ Excel อ่านไทยได้


def downloads(res, v, title):
    with st.popover("ดาวน์โหลด", icon=":material/download:", width="stretch"):
        st.download_button("รายงาน Word (.docx)",
                           export.report_docx(res["report"], f"Competitor Compare: {title}",
                                              f"เขียนเมื่อ {fmt_time(res['report_at'])} · ทุกตัวเลขมาจากข้อมูลที่ระบบดึงมา "
                                              "ลิงก์ [n] เปิดแหล่งที่มาได้"),
                           f"report_{res['report_id']}.docx",
                           "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                           icon=":material/description:", on_click="ignore", width="stretch")
        st.download_button("รายงาน Markdown (.md)", res["report"], "report.md", "text/markdown",
                           icon=":material/article:", on_click="ignore", width="stretch")
        st.download_button(f"ข้อมูลที่กรองแล้ว {len(v['df'])} รายการ (.csv)",
                           _csv(v["df"]) if not v["df"].empty else b"", "data.csv", "text/csv",
                           icon=":material/table:", on_click="ignore", width="stretch", disabled=v["df"].empty)


def follow(res):
    with st.popover("ติดตาม", icon=":material/notifications_active:", width="stretch"):
        st.caption("บันทึกชุดนี้ ระบบจะดึงข้อมูลใหม่ตามเวลาที่ตั้ง แล้วบอกว่าอะไรเปลี่ยน")
        watch_panel.save_form(res)
        nav.link("watch", "ตั้งเวลาและแจ้งเตือน")


def header(res):
    """ชื่อชุด + ความสดของข้อมูล"""
    top = [c for c in res["companies"] if c not in res.get("groups", {})]
    title = (f"{res['self_name']} vs " + ", ".join(c for c in top if c != res["self_name"])
             if res["self_name"] else " · ".join(top))
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
    return title, fresh


def show(res, on_report):
    title, fresh = header(res)
    head, b_new, b_dl = st.columns([5, 1.4, 1.4], vertical_alignment="center")
    head.markdown(f"## {title}")
    if b_new.button("วิเคราะห์ใหม่", icon=":material/add_chart:", type="primary", width="stretch"):
        nav.go("new")
    tools = st.columns([1.2, 1.2, 1.2, 4.4])  # เครื่องมือรอง: ตัวกรอง ติดตาม คำศัพท์
    with tools[0]:
        f = filter_bar(res)
    scope = describe(f)
    active = bool(scope)
    v = build_view(res, f)
    with b_dl:
        downloads(res, v, title)
    with tools[1]:
        follow(res)
    with tools[2]:
        glossary()
    with st.expander("ที่มาและความสดของข้อมูล", icon=":material/schedule:"):
        st.caption(" · ".join(fresh))
    if res.get("focus_label"):
        st.caption(f"วิเคราะห์เฉพาะเรื่อง: **{res['focus_label']}**")

    if active:
        c1, c2 = st.columns([6, 1], vertical_alignment="center")
        c1.info(f"กำลังกรอง: {scope} · เหลือ {len(v['df'])} จาก {len(res['df'])} รายการ",
                icon=":material/filter_alt:")
        c2.button("ล้าง", icon=":material/filter_alt_off:", on_click=reset_filters, width="stretch",
                  key="flt_clear")
    if v["df"].empty and v["fin"].empty and v["internal"].empty:
        st.warning("ไม่มีข้อมูลตามตัวกรองนี้ ลองขยายช่วงเวลาหรือกด “ล้าง”")
        return

    highlights(res, v)
    kpi_cards(v)
    has_gap = bool(v["self_name"]) and not v["gap"].empty
    names = ["สรุป"] + (["เรา vs คู่แข่ง"] if has_gap else []) + ["เจาะลึก", "ข้อมูลทั้งหมด"]
    renders = ([lambda: tab_summary(res, v, f, active, scope, on_report)]
               + ([lambda: tab_gap(v)] if has_gap else [])
               + [lambda: tab_deep(res, v), lambda: tab_data(v)])
    for tab, render in zip(st.tabs(names), renders):
        with tab:
            render()
