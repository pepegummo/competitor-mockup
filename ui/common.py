from contextlib import contextmanager
from datetime import datetime

import requests
import streamlit as st


def fmt_time(iso):
    return iso.replace("T", " ")[:16] if iso else "-"


def ago(iso):
    """เวลาที่ผ่านมาแบบอ่านง่าย เช่น "3 ชม.ที่แล้ว" (iso = เวลาเครื่อง)"""
    if not iso:
        return "-"
    secs = (datetime.now() - datetime.fromisoformat(str(iso)[:19])).total_seconds()
    if secs < 3600:
        return f"{max(int(secs // 60), 1)} นาทีที่แล้ว"
    if secs < 86400:
        return f"{int(secs // 3600)} ชม.ที่แล้ว"
    return f"{int(secs // 86400)} วันที่แล้ว"


@contextmanager
def friendly_errors():
    try:
        yield
    except RuntimeError as e:
        st.error(f"{e} เปิดไฟล์ `.env` ใส่ `LLM_API_KEY=...` แล้วรีสตาร์ทแอป")
    except requests.RequestException as e:
        st.error(f"เชื่อมต่อ LLM ไม่ได้ ({type(e).__name__}) ข่าวที่จัดหมวดแล้วถูกบันทึกไว้ "
                 "กดอีกครั้งจะทำต่อจากเดิม")
