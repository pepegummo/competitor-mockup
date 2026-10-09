"""ดูแลข้อมูล: รวมบริษัทที่ซ้ำกัน (ชื่อหุ้นเดียวกัน) และจัดหมวดข่าวเก่าใหม่ (ตรวจความเกี่ยวข้องย้อนหลัง)"""
import math

import streamlit as st

from core import db, process
from ui.common import friendly_errors


def _merge_section():
    st.markdown("**บริษัทซ้ำ** · ชื่อหุ้นเดียวกันแต่เป็นคนละแถว ข้อมูลจึงถูกดึงซ้ำ")
    groups = db.duplicate_groups()
    if not groups:
        st.caption("ไม่มีบริษัทซ้ำ")
        return
    for g in groups:
        symbol = g[0]["set_symbol"]
        docs = {r["name"]: r["docs"] for r in g}
        c1, c2 = st.columns([4, 1], vertical_alignment="bottom")
        keep = c1.radio(f"{symbol}: เก็บชื่อไหน", list(docs), format_func=lambda n: f"{n} ({docs[n]} รายการ)",
                        horizontal=True, key=f"dup_{symbol}")
        if c2.button("รวม", key=f"merge_{symbol}", width="stretch"):
            st.session_state.confirm_merge = symbol
        if st.session_state.get("confirm_merge") == symbol:
            others = [n for n in docs if n != keep]
            st.warning(f"ย้ายข่าว งบ และข้อมูลภายในของ {', '.join(others)} ไปไว้ที่ {keep} แล้วลบแถวเดิม "
                       f"(ชื่อเดิมจะเป็นชื่อเรียกของ {keep}) ย้อนกลับไม่ได้")
            y, n = st.columns(2)
            if y.button("ยืนยันรวม", type="primary", key=f"merge_yes_{symbol}", width="stretch"):
                moved = db.merge_companies(keep, others)
                st.session_state.pop("confirm_merge", None)
                st.toast(f"รวมเข้ากับ {keep} แล้ว ย้าย {moved} รายการ")
                st.rerun()
            if n.button("ยกเลิก", key=f"merge_no_{symbol}", width="stretch"):
                st.session_state.pop("confirm_merge", None)
                st.rerun()


def _recheck_section(names):
    st.markdown("**ตรวจข่าวเก่าว่าเกี่ยวกับบริษัทจริงไหม** · ข่าวที่ดึงมาก่อนมีตัวกรองข่าวชื่อชนกัน")
    ids = db.company_ids(names)
    if not ids:
        st.caption("เลือกบริษัทที่แถบซ้ายก่อน")
        return
    total, labeled = db.checked_relevance_count(ids)
    todo = total - labeled
    calls = math.ceil(todo / process.BATCH_SIZE)
    st.caption(f"{', '.join(names)}: ข่าว {total} รายการ จะถูกจัดหมวดและตรวจใหม่ {todo} รายการ "
               f"(ใช้ LLM ประมาณ {calls} ครั้ง) ข่าวที่ตรวจด้วยมือแล้วไม่ถูกแตะ")
    if st.button("จัดหมวดข่าวเก่าใหม่", icon=":material/refresh:", key="recheck", disabled=not todo):
        with friendly_errors(), st.status("กำลังจัดหมวดใหม่...") as status:
            db.reset_news_facts(ids)
            saved, skipped, dropped = process.classify_pending(ids, on_progress=lambda m: status.update(label=m))
            status.update(label=f"จัดหมวดใหม่ {saved} รายการ · ตัดข่าวที่ไม่เกี่ยว {dropped} รายการ"
                                + (f" · ข้าม {skipped} ชุด (กดอีกครั้งเพื่อลองใหม่)" if skipped else ""),
                          state="complete")
        st.caption("กดวิเคราะห์ใหม่เพื่อให้ตารางและรายงานใช้ผลล่าสุด")


def render(names):
    with st.expander("ดูแลข้อมูล", icon=":material/cleaning_services:"):
        _merge_section()
        st.divider()
        _recheck_section(names)
