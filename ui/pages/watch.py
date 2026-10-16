"""หน้าติดตามอัตโนมัติ: ชุดที่บันทึกไว้ ตั้งเวลา แจ้งเตือน"""
import streamlit as st

from ui import nav, state, watch_panel


def render():
    st.title("Auto Monitoring")
    if watch_panel.render(st.session_state.result, state.open_run):
        nav.go("overview")
