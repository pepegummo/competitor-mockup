"""เมนูของแอป (st.navigation): หน้าที่ไม่ได้เปิดจะไม่รัน · go("ask") เปลี่ยนหน้าจากโค้ด"""
import streamlit as st

PAGES = {}


def build():
    """สร้างหน้าทั้งหมด คืนโครงเมนูให้ st.navigation (เรียกทุกรอบจาก app.py)"""
    from ui.pages import accuracy, ask, companies, guide, internal, overview, setup, watch

    def page(key, render, title, icon, default=False):
        PAGES[key] = st.Page(render, title=title, icon=icon, url_path=key, default=default)
        return PAGES[key]

    return {
        "ใช้งาน": [page("overview", overview.render, "ภาพรวม", ":material/insights:", default=True),
                   page("new", setup.render, "วิเคราะห์ใหม่", ":material/add_chart:"),
                   page("ask", ask.render, "ถามข้อมูล", ":material/forum:"),
                   page("watch", watch.render, "ติดตามอัตโนมัติ", ":material/notifications_active:")],
        "ตั้งค่า": [
            page("internal", internal.render, "ข้อมูลภายใน", ":material/upload_file:"),
            page("companies", companies.render, "บริษัทและแหล่งข้อมูล", ":material/tune:"),
            page("accuracy", accuracy.render, "ตรวจความแม่น", ":material/fact_check:")],
        "ช่วยเหลือ": [page("guide", guide.render, "วิธีใช้", ":material/help:")],
    }


def go(key):
    st.switch_page(PAGES[key])


def link(key, label, icon=None, **kw):
    """ลิงก์ไปหน้าอื่น (ใช้ป้ายของเราแทนชื่อหน้า)"""
    st.page_link(PAGES[key], label=label, icon=icon or PAGES[key].icon, **kw)
