"""หน้าภาพรวม (หน้าแรก): ยังไม่มีผล → ชุดตัวอย่างกดครั้งเดียวเริ่มได้ · มีผล → สรุปสำคัญ การ์ดบริษัท รายงาน"""
import os

import streamlit as st

from core import db
from ui import nav, results, state
from ui.common import friendly_errors
from ui.labels import PRESETS


def _start_preset(names):
    """เริ่มวิเคราะห์ชุดตัวอย่างด้วยค่าเริ่มต้น (เทียบคู่แข่ง ทุกแหล่ง ไม่หาบริษัทในเครือเพื่อให้เร็ว)"""
    f = state.form()
    f.update(mode_input="compare", self_input=None, comp_input=list(names), focus_cats=[], focus_kw="")
    for k in state.FORM_KEYS:  # ให้หน้าวิเคราะห์ใหม่แสดงค่าชุดนี้
        st.session_state.pop(k, None)
    with friendly_errors():
        state.start_job(list(names), mode="compare", opts=state.make_opts(f), focus=state.make_focus(f))


def welcome():
    st.title("Competitor Compare")
    st.markdown("ดูว่าคู่แข่งทำอะไรอยู่ จากข่าว ประกาศตลาดหลักทรัพย์ รีวิวแอป และงบการเงิน "
                "สรุปเป็นรายงานพร้อมลิงก์ที่มาทุกข้อ")
    st.markdown("##### เริ่มเร็วด้วยชุดตัวอย่าง")
    busy = state.job_running()
    for col, (title, icon, names) in zip(st.columns(len(PRESETS)), PRESETS):
        with col.container(border=True):
            st.markdown(f"**{title}**")
            st.caption(" · ".join(names))
            if st.button("วิเคราะห์ชุดนี้", key=f"preset_{title}", icon=icon, disabled=busy, width="stretch"):
                _start_preset(names)
                st.rerun()
    c1, c2 = st.columns([1, 3], vertical_alignment="center")
    if c1.button("ตั้งค่าเอง", type="primary", icon=":material/add_chart:", width="stretch"):
        nav.go("new")
    c2.caption("เลือกบริษัทเอง เทียบกับบริษัทของเรา หรือให้ระบบหาคู่แข่งให้")

    st.markdown("##### ระบบทำอะไรบ้าง")
    steps = [
        ("1. ดึงข้อมูล", "ข่าว ข่าวแจ้งตลาด รีวิวแอป และงบการเงินล่าสุดจาก SET ของแต่ละบริษัท"),
        ("2. จัดหมวด", "LLM ตัดข่าวที่ไม่เกี่ยว แยกหมวดและน้ำเสียง (บวก/กลาง/ลบ) ข่าวที่เคยจัดแล้วไม่ถูกส่งซ้ำ"),
        ("3. สรุปผล", "นับตัวเลขเปรียบเทียบด้วยระบบ แล้วให้ LLM เขียนรายงานจากตัวเลขนั้น ถามต่อได้ในหน้าถามข้อมูล"),
    ]
    for col, (title, text) in zip(st.columns(3), steps):
        with col.container(border=True):
            st.markdown(f"**{title}**")
            st.caption(text)


def render():
    if os.environ.get("CC_DEMO"):
        st.info(f"โหมดเดโม · ข้อมูลชุดตัวอย่างใน `{db.DATA_DIR.name}/` (ผลวิเคราะห์ คำถามตัวอย่าง ตัวเลข SET "
                "เก็บไว้แล้ว เปิดได้โดยไม่ต้องใช้เน็ตหรือเครื่อง LLM) · คำถามใหม่และการวิเคราะห์ใหม่ยังต้องใช้เน็ต",
                icon=":material/slideshow:")
    if state.job_running():
        state.job_progress()
    for note in st.session_state.pop("job_notes", []):
        st.warning(note)

    res = st.session_state.result
    if not res or (res["df"].empty and res["fin"].empty):
        welcome()
        return
    results.show(res, state.on_new_report)
