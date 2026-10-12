"""เทสหน้าเว็บแบบ smoke: เปิดทุกหน้ากับสำเนาชุดเดโม (demo/app.db) แล้วต้องไม่มี error
ไม่ใช้เน็ต: รายชื่อหุ้น SET ถูกแทนด้วยรายการว่าง"""
import shutil
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from core import db
from core.sources import set_api
from ui import company_picker, state

DEMO = Path(__file__).resolve().parent.parent / "demo"


def _page(target):
    """สคริปต์ทดสอบ: ลงทะเบียนเมนูเหมือน app.py แล้ว render หน้าที่ต้องการตรง ๆ"""
    import streamlit as st

    from ui import nav, state as s
    from ui.pages import accuracy, ask, companies, internal, overview, setup, watch

    if "result" not in st.session_state:
        st.session_state.result = s.restore_last_result()
    st.navigation(nav.build(), position="hidden")
    target = st.session_state.get("_target", target)  # เทสเปลี่ยนหน้าได้ระหว่างรอบ
    {"overview": overview, "new": setup, "ask": ask, "watch": watch, "internal": internal,
     "companies": companies, "accuracy": accuracy}[target].render()


@pytest.fixture
def demo_db(tmp_path, monkeypatch):
    shutil.copy(DEMO / "app.db", tmp_path / "app.db")
    shutil.copy(DEMO / "last_run.json", tmp_path / "last_run.json")
    monkeypatch.setattr(db, "DATA_DIR", tmp_path)
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "app.db")
    monkeypatch.setattr(db, "DATABASE_URL", "")  # ชุดเดโมเป็นไฟล์ SQLite
    monkeypatch.setattr(state, "LAST_RUN", tmp_path / "last_run.json")
    monkeypatch.setenv("CC_DEMO", "1")
    monkeypatch.setenv("LLM_REPLAY", "1")
    monkeypatch.setattr(company_picker, "_listed", lambda: {})
    monkeypatch.setattr(set_api, "listed_companies", lambda: {})
    db.init_db()


def run(target):
    at = AppTest.from_function(_page, args=(target,), default_timeout=60)
    return at.run()


@pytest.mark.parametrize("target", ["overview", "new", "ask", "watch", "internal", "companies", "accuracy"])
def test_every_page_opens(demo_db, target):
    at = run(target)
    assert not at.exception, at.exception


def test_overview_shows_summary_first(demo_db):
    at = run("overview")
    text = " ".join(m.value for m in at.markdown)
    assert "สิ่งที่ควรรู้" in text
    assert [t.label for t in at.tabs][:1] == ["สรุป"]
    assert "ถามข้อมูล" not in [t.label for t in at.tabs]  # ย้ายไปเป็นหน้าแยก


def test_start_disabled_until_two_competitors(demo_db):
    at = run("new")
    at.multiselect(key="comp_input").set_value(["MC"]).run()
    start = next(b for b in at.button if b.label == "เริ่มวิเคราะห์")
    assert start.disabled
    assert "คู่แข่ง 2–5 ราย" in " ".join(m.value for m in at.markdown)


def test_form_remembered_across_pages(demo_db):
    at = run("new")
    at.multiselect(key="comp_input").set_value(["AP", "KCE"]).run()
    at.session_state["_target"] = "ask"  # ไปหน้าอื่น: Streamlit ลบ state ของ widget ที่ไม่ได้แสดง
    at.run()
    at.session_state["_target"] = "new"
    at.run()
    assert at.multiselect(key="comp_input").value == ["AP", "KCE"]
