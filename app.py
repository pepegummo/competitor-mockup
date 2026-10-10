"""Competitor Compare: หน้าเว็บ Streamlit
เมนูอยู่ใน ui/nav.py · แต่ละหน้าอยู่ใน ui/pages/ · สถานะที่ใช้ร่วมกัน (ผลที่เปิดอยู่ ฟอร์ม งานเบื้องหลัง) อยู่ใน ui/state.py"""
import streamlit as st

from core import db
from ui import nav, state

st.set_page_config(page_title="Competitor Compare", page_icon="📊", layout="wide")
db.init_db()

if "result" not in st.session_state:
    st.session_state.result = state.restore_last_result()

page = st.navigation(nav.build())

with st.sidebar:
    res = st.session_state.result
    if res:
        st.caption(f":material/visibility: เปิดอยู่: **{state.result_title(res)}**")
    state.job_watch()  # บอกความคืบหน้าทุกหน้า และเปิดผลให้เองเมื่อเสร็จ

if msg := st.session_state.pop("toast", None):
    st.toast(msg, icon=":material/check_circle:")

page.run()
