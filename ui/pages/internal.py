"""หน้าข้อมูลภายใน: อัปโหลดตัวเลขของบริษัท (CSV/Excel)"""
import streamlit as st

from ui import internal_panel, state


def render():
    st.title("Internal Data")
    if "internal_llm" not in st.session_state:  # widget ถูกลบเมื่ออยู่หน้าอื่น คืนค่าจากที่จำไว้
        st.session_state.internal_llm = state.internal_llm_on()
    res = st.session_state.result
    self_name = state.upcoming()[1] or (res or {}).get("self_name")
    internal_panel.render(self_name)
    st.session_state.internal_llm_on = st.session_state.internal_llm
