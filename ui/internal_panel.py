"""อัปโหลดข้อมูลภายในของบริษัท (CSV / Excel) เพื่อเทียบกับคู่แข่งและใช้ในรายงาน"""
import pandas as pd
import streamlit as st

from core import db, internal


def _upload(self_name):
    up = st.file_uploader("ไฟล์ CSV หรือ Excel", type=["csv", "xlsx", "xls"], key="internal_file")
    if not up:
        return
    try:
        rows, problems = internal.to_long(internal.read_file(up.name, up.getvalue()))
    except (ValueError, ImportError) as e:
        st.error(str(e))
        return
    rows, unmatched = internal.match_companies(rows, db.company_names(), self_name)
    st.dataframe(pd.DataFrame(rows).rename(columns={"company": "บริษัท", "metric": "ตัวชี้วัด", "value": "ค่า",
                                                    "unit": "หน่วย", "period": "ช่วงเวลา"}),
                 hide_index=True, width="stretch", height=min(38 + 35 * len(rows), 260))
    for p in problems[:5]:
        st.caption(f":orange[ข้าม {p}]")
    if unmatched:
        st.warning(f"ชื่อเหล่านี้ไม่ตรงกับบริษัทในระบบ: {', '.join(unmatched)} — บันทึกได้ แต่จะใช้เมื่อวิเคราะห์บริษัท"
                   "ชื่อนี้เท่านั้น" + ("" if self_name else " (ใช้ “เรา” ได้เมื่อเลือกโหมดที่มีบริษัทของเรา)"),
                   icon=":material/warning:")
    if st.button(f"บันทึก {len(rows)} ค่า", type="primary", icon=":material/save:"):
        db.save_internal(rows)
        st.session_state.pop("internal_file", None)
        st.toast("บันทึกข้อมูลภายในแล้ว")
        st.rerun()


def render(self_name):
    current = db.internal_metrics()
    title = "ข้อมูลภายในบริษัท" + (f" ({len(current)} ค่า)" if not current.empty else "")
    with st.expander(title, icon=":material/upload_file:", expanded=True):
        st.caption("อัปโหลดตัวเลขที่มีแค่ในบริษัท เช่น ยอดขาย ลูกค้าใหม่ NPS ส่วนแบ่งตลาด (ของเราหรือที่ประเมินคู่แข่ง) "
                   "ระบบจะเพิ่มในตาราง “เรา vs คู่แข่ง” แท็บเจาะลึก และในรายงาน · ใช้ “เรา” แทนชื่อบริษัทเราได้")
        c1, c2 = st.columns([3, 1], vertical_alignment="center")
        c1.caption("แบบยาว: คอลัมน์ บริษัท, ตัวชี้วัด, ค่า, หน่วย, ช่วงเวลา · "
                   "แบบกว้าง: คอลัมน์แรกเป็นบริษัท คอลัมน์อื่นเป็นตัวชี้วัด")
        c2.download_button("ไฟล์ตัวอย่าง", internal.TEMPLATE.to_csv(index=False).encode("utf-8-sig"),
                           "internal_template.csv", "text/csv", icon=":material/download:", on_click="ignore",
                           width="stretch")
        _upload(self_name)
        if not current.empty:
            st.markdown("**ที่บันทึกไว้**")
            st.dataframe(current.drop(columns=["uploaded_at"]).rename(
                columns={"company": "บริษัท", "metric": "ตัวชี้วัด", "value": "ค่า", "unit": "หน่วย",
                         "period": "ช่วงเวลา"}), hide_index=True, width="stretch")
            if st.button("ลบข้อมูลภายในทั้งหมด", icon=":material/delete:"):
                db.clear_internal()
                st.rerun()
        st.checkbox("ให้ LLM ใช้ข้อมูลภายในตอนเขียนรายงาน", value=True, key="internal_llm",
                    help="ข้อมูลเก็บในเครื่องนี้ (data/app.db) แต่ถ้าเปิดไว้ ตัวเลขจะถูกส่งไปยังเซิร์ฟเวอร์ LLM "
                         "พร้อมตารางอื่นตอนเขียนรายงาน ปิดไว้ถ้าเป็นข้อมูลลับที่ห้ามส่งออกนอกบริษัท")
