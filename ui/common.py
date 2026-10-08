from contextlib import contextmanager

import requests
import streamlit as st


def fmt_time(iso):
    return iso.replace("T", " ")[:16] if iso else "-"


@contextmanager
def friendly_errors():
    try:
        yield
    except RuntimeError as e:
        st.error(f"{e} เปิดไฟล์ `.env` ใส่ `LLM_API_KEY=...` แล้วรีสตาร์ทแอป")
    except requests.RequestException as e:
        st.error(f"เชื่อมต่อ LLM ไม่ได้ ({type(e).__name__}) ข่าวที่จัดหมวดแล้วถูกบันทึกไว้ "
                 "กดอีกครั้งจะทำต่อจากเดิม")
