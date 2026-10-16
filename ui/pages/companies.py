"""หน้าบริษัทและแหล่งข้อมูล: บริษัทในเครือ การ์ดแหล่งข้อมูลของบริษัทที่จะวิเคราะห์ และดูแลข้อมูล"""
import streamlit as st

from ui import company_panel, group_panel, maintenance_panel, nav, state


def render():
    st.title("Companies & Sources")
    names, self_name = state.upcoming()
    f = state.form()
    if not names:
        st.info("ยังไม่ได้เลือกบริษัท เลือกในหน้าวิเคราะห์ใหม่ก่อน แล้วตั้งค่าแหล่งข้อมูลของแต่ละบริษัทได้ที่นี่",
                icon=":material/info:")
        nav.link("new", "ไปหน้าวิเคราะห์ใหม่")
    else:
        st.caption("บริษัทที่จะวิเคราะห์รอบถัดไป: " + ", ".join(names) + " · เปลี่ยนรายชื่อได้ในหน้าวิเคราะห์ใหม่")
        members = {}
        if f["with_groups"]:
            group_panel.render(names)
            group_panel.register(names)
            members = group_panel.picked(names)
        company_panel.render(names + list(members), self_name, f["src_pick"] or [], True, members)
    st.subheader("Maintenance", divider="gray")
    maintenance_panel.render(names)
