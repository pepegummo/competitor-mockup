"""หน้าวิธีใช้: ขั้นตอนใช้งาน 4 ขั้น (มีปุ่มพาไปหน้านั้น) · คำศัพท์ · หน้าไหนสำหรับใคร"""
import streamlit as st

from ui import nav
from ui.labels import GLOSSARY

STEPS = [
    ("1", "Choose companies", "ไปหน้า “New Analysis” เลือก 2–5 บริษัท (หรือบริษัทของเรากับคู่แข่ง หรือให้ระบบหาคู่แข่งให้) "
     "ขั้นอื่นไม่บังคับ แล้วกด “เริ่มวิเคราะห์”", "new", "ไปหน้าวิเคราะห์ใหม่"),
    ("2", "Wait for the analysis", "ระบบดึงข่าว ประกาศตลาด รีวิวแอป และงบการเงิน แล้วให้ LLM จัดหมวดและน้ำเสียง ปกติ 1–3 นาที "
     "ทำงานเบื้องหลัง ไปหน้าอื่นระหว่างรอได้ เสร็จแล้วระบบเปิดผลให้เอง", "overview", "ดูความคืบหน้าที่ภาพรวม"),
    ("3", "Read the results", "หน้า “Overview” เรียงจากสรุปไปรายละเอียด: ข้อควรรู้ → การ์ดต่อบริษัท → แท็บ Summary / Us vs Competitors / "
     "Deep Dive / All Data ทุกข้อในรายงานมีลิงก์ [n] ไปยังที่มา ใช้ “ตัวกรอง” ลดข้อมูลได้", "overview", "ไปหน้าภาพรวม"),
    ("4", "Ask or monitor", "ถามคำถามเพิ่มจากข้อมูลที่เก็บไว้ในหน้า “Ask Data” "
     "หรือบันทึกชุดบริษัทไว้ให้ระบบดึงข้อมูลใหม่ทุกวันและแจ้งว่าอะไรเปลี่ยนในหน้า “Auto Monitoring”", "ask", "ไปหน้าถามข้อมูล"),
]


def render():
    st.title("How to Use")
    st.caption("ใช้เวลาไม่กี่นาที ทำตาม 4 ขั้นนี้ได้เลย")
    for num, title, text, page, label in STEPS:
        with st.container(border=True):
            c1, c2 = st.columns([5, 1.6], vertical_alignment="center")
            c1.markdown(f"**Step {num} · {title}**")
            c1.caption(text)
            with c2:
                nav.link(page, label)

    st.subheader("Which Page to Use", divider="gray")
    st.markdown(
        "- **ใช้ประจำ:** Overview · New Analysis · Ask Data · Auto Monitoring\n"
        "- **ตั้งค่า (ใช้เมื่อจำเป็น):** Internal Data (อัปโหลดตัวเลข/เอกสารของเราเอง) · "
        "Companies & Sources (แก้ชื่อแอป ชื่อหุ้น รวมบริษัทซ้ำ) · Accuracy Check (ตรวจว่า LLM ตัดสินข่าวถูกไหม)")

    st.subheader("Glossary", divider="gray")
    with st.expander("ความหมายของคำที่เจอในรายงาน", icon=":material/help:"):
        for term, text in GLOSSARY.items():
            st.markdown(f"**{term}** — {text}")
