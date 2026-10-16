"""แท็บเจาะลึก: เทียบทั้งหมวดธุรกิจ SET และราคาหุ้นหลังข่าว (ข้อมูลตลาด ไม่ผ่าน LLM)"""
import streamlit as st

from core import benchmark, impact
from ui import charts, insights
from ui.common import friendly_errors
from ui.labels import SENTIMENT_TH


def market_tables(v):
    """อันดับในหมวดและราคาหุ้นหลังข่าว (ตามตัวกรอง) สำหรับส่งให้รายงาน/คำถาม"""
    companies = benchmark.symbols_of(v["companies"])
    if not companies:
        return {"sector": None, "price": None}
    return {"sector": benchmark.table(companies), "price": impact.events(v["df"], companies)}


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
    st.markdown("##### Biggest Stock Moves After News")
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
