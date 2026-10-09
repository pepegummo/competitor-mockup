"""แท็บเจาะลึก: หมวดข่าว รีวิวแอป แนวโน้มรายสัปดาห์ ข้อมูลภายใน"""
import pandas as pd
import streamlit as st

from core import analyze
from ui import charts, insights
from ui.labels import CATEGORY_TH


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
