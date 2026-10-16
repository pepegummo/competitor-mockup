"""หน้าถามข้อมูล: ถามเป็นภาษาไทยเกี่ยวกับผลวิเคราะห์ที่เปิดอยู่"""
import streamlit as st

from ui import nav, state
from ui.sections import ask as ask_section


def render():
    st.title("Ask Data")
    res = st.session_state.result
    if not res or res["df"].empty:
        st.info("ยังไม่มีข้อมูลให้ถาม วิเคราะห์บริษัทที่สนใจก่อน แล้วกลับมาถามที่นี่", icon=":material/info:")
        nav.link("new", "Go to New Analysis")
        return
    st.markdown(f"ถามเกี่ยวกับ **{state.result_title(res)}**")
    ask_section.tab_ask(res)
