"""หน้าตรวจความแม่น: ผู้ตรวจกดทีละข่าวว่าระบบตัดสินถูกไหม"""
import streamlit as st

from ui import accuracy_panel


def render():
    st.title("Accuracy Check")
    accuracy_panel.render()
