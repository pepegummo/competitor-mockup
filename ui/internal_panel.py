"""อัปโหลดข้อมูลภายในของบริษัท: ตัวเลข (CSV / Excel) เพื่อเทียบกับคู่แข่งและใช้ในรายงาน
และเอกสาร PDF ให้แท็บถามข้อมูลค้นได้"""
import pandas as pd
import streamlit as st

from core import db, internal, ocr, process


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
    if st.button(f"Save {len(rows)} values", type="primary", icon=":material/save:"):
        db.save_internal(rows)
        st.session_state.pop("internal_file", None)
        st.toast("บันทึกข้อมูลภายในแล้ว")
        st.rerun()


def render(self_name):
    current = db.internal_metrics()
    st.caption("อัปโหลดตัวเลขที่มีแค่ในบริษัท เช่น ยอดขาย ลูกค้าใหม่ NPS ส่วนแบ่งตลาด (ของเราหรือที่ประเมินคู่แข่ง) "
               "ระบบจะเพิ่มในตาราง “เรา vs คู่แข่ง” แท็บเจาะลึก และในรายงาน · ใช้ “เรา” แทนชื่อบริษัทเราได้")
    c1, c2 = st.columns([3, 1], vertical_alignment="center")
    c1.caption("แบบยาว: คอลัมน์ บริษัท, ตัวชี้วัด, ค่า, หน่วย, ช่วงเวลา · "
               "แบบกว้าง: คอลัมน์แรกเป็นบริษัท คอลัมน์อื่นเป็นตัวชี้วัด")
    c2.download_button("Sample file", internal.TEMPLATE.to_csv(index=False).encode("utf-8-sig"),
                       "internal_template.csv", "text/csv", icon=":material/download:", on_click="ignore",
                       width="stretch")
    _upload(self_name)
    if not current.empty:
        st.markdown("**ที่บันทึกไว้**")
        st.dataframe(current.drop(columns=["uploaded_at"]).rename(
            columns={"company": "บริษัท", "metric": "ตัวชี้วัด", "value": "ค่า", "unit": "หน่วย",
                     "period": "ช่วงเวลา"}), hide_index=True, width="stretch")
        if st.button("Delete all internal data", icon=":material/delete:"):
            db.clear_internal()
            st.rerun()
    st.checkbox("ให้ LLM ใช้ข้อมูลภายในตอนเขียนรายงาน", key="internal_llm",
                help="ข้อมูลเก็บในเครื่องนี้ (data/app.db) แต่ถ้าเปิดไว้ ตัวเลขจะถูกส่งไปยังเซิร์ฟเวอร์ LLM "
                     "พร้อมตารางอื่นตอนเขียนรายงาน ปิดไว้ถ้าเป็นข้อมูลลับที่ห้ามส่งออกนอกบริษัท")
    st.divider()
    _pdf_section(self_name)


def _pdf_section(self_name):
    st.markdown("**เอกสาร PDF**")
    st.caption("เช่น รายงานภายใน โบรชัวร์หรือใบราคาของคู่แข่ง ระบบอ่านข้อความ (หน้าสแกนใช้ OCR) แล้วให้ LLM สรุปทีละส่วน "
               "ถามเรื่องในเอกสารได้ที่แท็บถามข้อมูล · ไม่นับในตารางและกราฟเปรียบเทียบ · "
               "เนื้อหาจะถูกส่งไปยังเซิร์ฟเวอร์ LLM")
    up = st.file_uploader("ไฟล์ PDF", type=["pdf"], key="internal_pdf")
    if up:
        _pdf_upload(up, self_name)
    saved = db.uploaded_documents()
    if not saved.empty:
        st.markdown("**เอกสารที่บันทึกไว้**")
        for r in saved.itertuples():
            c1, c2 = st.columns([5, 1], vertical_alignment="center")
            c1.markdown(f"{r.source_name} · {r.company} · {r.parts} ส่วน · {r.uploaded_at[:16].replace('T', ' ')}")
            if c2.button("Delete", key=f"del_pdf_{r.Index}", icon=":material/delete:"):
                db.delete_uploaded(r.source_name, r.company)
                _refresh_result()
                st.rerun()


def _refresh_result():
    """ผลวิเคราะห์ที่เปิดอยู่เก็บ df ไว้ตอนเปิด โหลดใหม่ให้แท็บถามข้อมูลเห็น/ไม่เห็นเอกสารทันที"""
    from ui import state
    if st.session_state.get("result"):
        st.session_state.result = state.restore_last_result() or st.session_state.result


def _pdf_upload(up, self_name):
    data = up.getvalue()
    try:
        total = ocr.page_count(data)
    except ValueError as e:
        st.error(str(e))
        return
    names = db.company_names()
    if not names:
        st.info("ยังไม่มีบริษัทในระบบ วิเคราะห์อย่างน้อย 1 รอบก่อน แล้วค่อยแนบเอกสารให้บริษัทนั้น")
        return
    c1, c2, c3 = st.columns([3, 1, 1])
    company = c1.selectbox("เป็นเอกสารของบริษัท", names,
                           index=names.index(self_name) if self_name in names else 0, key="internal_pdf_company")
    first, last = 1, total
    if total > ocr.MAX_PAGES:
        first = c2.number_input("หน้าเริ่ม", 1, total, 1, key="internal_pdf_first")
        last = c3.number_input("หน้าสุดท้าย", first, total, min(first + ocr.MAX_PAGES - 1, total),
                               key="internal_pdf_last")
        st.caption(f"ไฟล์มี {total} หน้า อ่านได้ครั้งละ {ocr.MAX_PAGES} หน้า "
                   "อ่านช่วงอื่นต่อได้โดยอัปโหลดไฟล์เดิมแล้วเปลี่ยนช่วงหน้า")
        if last - first + 1 > ocr.MAX_PAGES:
            st.warning(f"เลือกไว้ {last - first + 1} หน้า เกิน {ocr.MAX_PAGES} หน้า", icon=":material/warning:")
            return
    if not st.button("Read and save", type="primary", icon=":material/description:"):
        return
    with st.spinner(f"กำลังอ่าน {up.name} หน้า {first}–{last} …"):
        try:
            res = internal.save_pdf(company, up.name, data, first, last)
        except ValueError as e:
            st.error(str(e))
            return
    if not res["parts"]:
        st.warning("ไม่พบข้อความที่อ่านได้" + (" หน้าเหล่านี้เป็นภาพ และเครื่องนี้ยังไม่มี OCR (ตั้ง OCR_URL หรือลง Tesseract)"
                                               if not res["ocr"] else ""), icon=":material/warning:")
        return
    if not res["added"]:
        st.info("เอกสารช่วงนี้บันทึกไว้แล้ว")
        return
    with st.spinner("LLM กำลังสรุปเนื้อหาแต่ละส่วน …"):
        process.classify_pending([res["company_id"]])
    _refresh_result()
    st.session_state.pop("internal_pdf", None)
    st.toast(f"บันทึก {res['added']} ส่วน · อ่านจากข้อความ {res['text']} หน้า · OCR {res['ocr']} หน้า"
             + (f" · อ่านไม่ได้ {res['skipped']} หน้า" if res["skipped"] else ""))
    st.rerun()
