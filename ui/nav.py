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
        "Workspace": [page("overview", overview.render, "Overview", ":material/insights:", default=True),
                   page("new", setup.render, "New Analysis", ":material/add_chart:"),
                   page("ask", ask.render, "Ask Data", ":material/forum:"),
                   page("watch", watch.render, "Auto Monitoring", ":material/notifications_active:")],
        "Settings": [
            page("internal", internal.render, "Internal Data", ":material/upload_file:"),
            page("companies", companies.render, "Companies & Sources", ":material/tune:"),
            page("accuracy", accuracy.render, "Accuracy Check", ":material/fact_check:")],
        "Help": [page("guide", guide.render, "How to Use", ":material/help:")],
    }


def go(key):
    st.switch_page(PAGES[key])


def link(key, label, icon=None, **kw):
    """ลิงก์ไปหน้าอื่น (ใช้ป้ายของเราแทนชื่อหน้า)"""
    st.page_link(PAGES[key], label=label, icon=icon or PAGES[key].icon, **kw)
