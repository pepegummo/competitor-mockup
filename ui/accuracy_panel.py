"""ตรวจความแม่น: ผู้ใช้ตรวจข่าวทีละข่าวว่าระบบตัดสินถูกไหม (เกี่ยวกับบริษัทไหม หมวด น้ำเสียง)
ผลใช้วัดความแม่นเป็นตัวเลข และเป็นตัวอย่างให้ LLM ตอนจัดหมวดรอบถัดไป"""
import streamlit as st

from core import accuracy, db
from ui.labels import CATEGORY_TH, SENTIMENT_TH

QUEUE = 20
NEWS_CATEGORIES = ["product_price", "promotion", "news_pr", "financial", "hr", "other"]  # ข่าวไม่มีหมวดรีวิว


def _save(item, relevant):
    fid = item["fact_id"]
    if relevant:
        db.save_label(fid, True, st.session_state[f"lab_cat_{fid}"], st.session_state[f"lab_sent_{fid}"])
    else:
        db.save_label(fid, False)
    st.session_state.label_queue.pop(0)


def _skip():
    st.session_state.label_queue.pop(0)


def _metrics():
    m = accuracy.metrics()
    cards = [
        ("ข่าวที่เก็บไว้ เกี่ยวจริง", m.get("kept_ok"), m.get("kept_n", 0), "ระบบบอกว่าเกี่ยว และผู้ตรวจเห็นด้วย"),
        ("ข่าวที่ตัดออก ไม่เกี่ยวจริง", m.get("dropped_ok"), m.get("dropped_n", 0),
         "ระบบตัดออกเพราะชื่อตรงแต่เป็นเรื่องอื่น และผู้ตรวจเห็นด้วย"),
        ("จับข่าวไม่เกี่ยวได้ (ประมาณ)", m.get("recall"), None,
         "ข่าวไม่เกี่ยวทั้งหมด ระบบตัดได้กี่ % · ปรับตามสัดส่วนจริงในฐานข้อมูล เพราะคิวตรวจดึงข่าวที่ตัดออกมามากกว่าปกติ"),
        ("หมวดถูก", m.get("category_ok"), m.get("category_n", 0), "เฉพาะข่าวที่เกี่ยวจริง"),
        ("น้ำเสียงถูก", m.get("sentiment_ok"), m.get("sentiment_n", 0), "เฉพาะข่าวที่เกี่ยวจริง"),
    ]
    for col, (label, value, n, help_) in zip(st.columns(len(cards)), cards):
        col.metric(label, f"{value:.0f}%" if value is not None else "–", help=help_, border=True)
        if n is not None:
            col.caption(f"จาก {n} ข่าว" + ("" if n >= accuracy.MIN_LABELS else f" (ต้องมีอย่างน้อย {accuracy.MIN_LABELS})"))
    return m


def _card(item):
    fid = item["fact_id"]
    kept = item["category"] != "irrelevant"
    with st.container(border=True):
        st.caption(f"{item['company']}" + (f" · {item['business']}" if item["business"] else "")
                   + f" · เหลือในคิว {len(st.session_state.label_queue)}")
        st.markdown(f"**[{item['title']}]({item['url']})**" if item["url"] else f"**{item['title']}**")
        if item["summary"]:
            st.caption(item["summary"])
        verdict = (f"เกี่ยวกับ {item['company']} · หมวด {CATEGORY_TH.get(item['category'], item['category'])} · "
                   f"น้ำเสียง{SENTIMENT_TH.get(item['sentiment'], item['sentiment'])}" if kept
                   else f"ไม่ใช่เรื่องของ {item['company']} (ตัดออก ไม่นับในการวิเคราะห์)")
        st.markdown(f"ระบบตัดสิน: **{verdict}**")
        c1, c2 = st.columns(2)
        cat = item["category"] if item["category"] in NEWS_CATEGORIES else "news_pr"
        c1.selectbox("หมวดที่ถูก", NEWS_CATEGORIES, index=NEWS_CATEGORIES.index(cat), format_func=CATEGORY_TH.get,
                     key=f"lab_cat_{fid}")
        sents = list(SENTIMENT_TH)
        c2.selectbox("น้ำเสียงที่ถูก", sents, index=sents.index(item["sentiment"]) if item["sentiment"] in sents else 1,
                     format_func=SENTIMENT_TH.get, key=f"lab_sent_{fid}")
        b1, b2, b3 = st.columns([2, 2, 1])
        b1.button(f"เกี่ยวกับ {item['company']}", type="primary", icon=":material/check:", width="stretch",
                  on_click=_save, args=(item, True), key=f"lab_yes_{fid}",
                  help="บันทึกพร้อมหมวดและน้ำเสียงที่เลือกด้านบน")
        b2.button("ไม่เกี่ยว (ชื่อตรงแต่เป็นเรื่องอื่น)", icon=":material/close:", width="stretch",
                  on_click=_save, args=(item, False), key=f"lab_no_{fid}")
        b3.button("ข้าม", width="stretch", on_click=_skip, key=f"lab_skip_{fid}")


def render():
    st.caption("ตรวจว่าระบบตัดสินข่าวถูกไหม ทีละข่าว ผลใช้วัดความแม่นเป็นตัวเลข และระบบจะใช้ข่าวที่ตรวจแล้ว"
               "เป็นตัวอย่างให้ LLM ตอนจัดหมวดรอบถัดไป (ยิ่งตรวจ ระบบยิ่งตัดสินแบบที่องค์กรต้องการ)")
    m = _metrics()
    if not st.session_state.get("label_queue"):
        st.session_state.label_queue = db.label_queue(QUEUE)
    if st.session_state.label_queue:
        _card(st.session_state.label_queue[0])
    else:
        st.success("ตรวจครบทุกข่าวแล้ว" if m["labeled"] else "ยังไม่มีข่าวให้ตรวจ กดวิเคราะห์ก่อน")
    wrong = accuracy.mistakes()
    if not wrong.empty:
        with st.expander(f"ข่าวที่ระบบตัดสินต่างจากผู้ตรวจ ({len(wrong)})", icon=":material/rule:"):
            st.dataframe(wrong, hide_index=True, width="stretch",
                         column_order=["company", "ผิดเรื่อง", "title", "category", "human_category", "sentiment",
                                       "human_sentiment"],
                         column_config={"company": "บริษัท", "title": st.column_config.TextColumn("หัวข้อ", width="large"),
                                        "category": "หมวด (ระบบ)", "human_category": "หมวด (ผู้ตรวจ)",
                                        "sentiment": "น้ำเสียง (ระบบ)", "human_sentiment": "น้ำเสียง (ผู้ตรวจ)"})
