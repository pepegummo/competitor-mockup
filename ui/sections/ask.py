"""แท็บถามข้อมูล: ถามเป็นภาษาไทย ตอบจากข้อมูลที่เก็บไว้พร้อมลิงก์ที่มา"""
import streamlit as st

from core import ask, benchmark, impact
from ui.common import friendly_errors
from ui.labels import SENTIMENT_TH


def _examples(res):
    first = res["self_name"] or res["companies"][0]
    out = [f"{first} เปิดตัวสินค้าหรือแคมเปญอะไรบ้าง", "ใครมีโปรโมชันหรือสินค้าใหม่ใน 30 วันล่าสุด"]
    if benchmark.symbols_of(res["companies"]):
        out += ["หุ้นตัวไหนขยับแรงหลังข่าว เป็นข่าวอะไร", f"อัตรากำไรของ {first} อยู่อันดับไหนในหมวด"]
    return out


def _ask_later(question):
    st.session_state.ask_pending = question


def tab_ask(res):
    st.caption("ตอบจากข้อมูลที่ระบบเก็บไว้ของบริษัทในผลนี้เท่านั้น (ข่าว ประกาศ SET รีวิว งบ อันดับในหมวด ราคาหุ้น) "
               "ไม่ใช้ความรู้ของ LLM · ทุกข้อมีลิงก์ที่มา · ไม่มีข้อมูลจะตอบว่าไม่มี · ใช้ LLM 2 ครั้งต่อคำถาม")
    key = f"ask_history_{res.get('report_id')}"
    history = st.session_state.setdefault(key, [])
    cols = st.columns(len(_examples(res)))
    for i, (col, q) in enumerate(zip(cols, _examples(res))):
        col.button(q, key=f"ask_ex_{i}", on_click=_ask_later, args=(q,), width="stretch")
    question = st.chat_input("ถามเกี่ยวกับคู่แข่ง เช่น “AP เปิดโครงการใหม่อะไรบ้าง”", key="ask_input")
    question = question or st.session_state.pop("ask_pending", None)
    # เรียงเก่า → ใหม่ แบบแชต: คำถามล่าสุดอยู่ล่างสุดติดช่องพิมพ์ (หน้าเลื่อนลงล่างเองหลังส่ง)
    for h in history:
        _show_question(h["q"])
        _show_answer(h)
    if question:
        _show_question(question)
        companies = benchmark.symbols_of(res["companies"])
        with friendly_errors(), st.spinner("กำลังค้นข้อมูลที่เก็บไว้และเขียนคำตอบ..."):
            out = ask.answer(question, res["df"], res["companies"], fin=res["fin"],
                             sector=benchmark.table(companies) if companies else None,
                             price=impact.events(res["df"], companies) if companies else None)
            history.append({"q": question, **out})
            _show_answer(history[-1])


def _show_question(q):
    with st.chat_message("user"):
        st.markdown(q)


def _show_answer(h):
    with st.chat_message("assistant"):
        st.markdown(h["answer"])
        f = h["filters"]
        scope = [", ".join(f["companies"]) or "ทุกบริษัท"]
        if f.get("sentiments"):
            scope.append("ข่าว" + "/".join(SENTIMENT_TH[x] for x in f["sentiments"]))
        if f["keywords"]:
            scope.append("คำค้น " + ", ".join(f["keywords"]))
        if f["days"]:
            scope.append(f"{f['days']} วันล่าสุด")
        st.caption(f"ใช้ {h['used']} รายการ · ค้นจาก: {' · '.join(scope)}"
                   + (" · ค้นด้วยความหมาย + คำค้น" if h.get("semantic") else " · ค้นด้วยคำค้นอย่างเดียว")
                   + (" · รวมตัวเลขงบ/อันดับ/ราคาหุ้น" if f["needs_numbers"] else "")
                   + f" · LLM {h['llm_calls']} ครั้ง")
