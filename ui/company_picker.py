"""รายชื่อบริษัทให้เลือก: บริษัทที่เคยวิเคราะห์ (บนสุด) + หุ้นสามัญ SET/mai ทั้งหมด · บริษัทนอกตลาดพิมพ์เองได้
ค่าที่เลือกจากรายชื่อ SET คือชื่อหุ้น (เช่น MC) ซึ่ง profile.suggest_profiles ใช้ยึดตัวตนกับทะเบียน SET"""
import streamlit as st

from core import benchmark, db, profile
from core.sources import SourceSkipped, set_api


@st.cache_data(ttl=86400, show_spinner=False)
def _listed():
    """{ชื่อหุ้น: ชื่อบริษัทแบบสั้น} ถ้า SET ใช้ไม่ได้จะ raise (st.cache_data ไม่จำ error รอบหน้าลองใหม่)"""
    return {k: profile.short_name(v["nameTH"]) or profile.short_name(v["nameEN"])
            for k, v in sorted(set_api.listed_companies().items())}


def options(selected=()):
    """คืน (ตัวเลือก, ป้ายของแต่ละตัวเลือก) · selected = ค่าที่เลือกอยู่ ต้องอยู่ในตัวเลือกเสมอ"""
    history = db.analyzed_companies()
    labels = {}
    for h in history:  # ชื่อที่ต่างจากชื่อหุ้นแสดงชื่อหุ้นต่อท้าย เช่น "AIS · ADVANC"
        same = h["set_symbol"].casefold() in ("", h["name"].casefold())
        labels[h["name"]] = h["name"] if same else f"{h['name']} · {h['set_symbol']}"
    if not history:
        labels = {n: n for n in ("AIS", "True", "NT")}  # DB ใหม่ ยังไม่มีประวัติ
    covered = {h["set_symbol"] for h in history} | set(labels)
    try:
        listed = _listed()
    except SourceSkipped:
        listed = {}
    for symbol, name in listed.items():
        if symbol not in covered:
            labels[symbol] = f"{symbol} · {name}" if name else symbol
    for n in selected:
        if n and n not in labels:
            labels[n] = n
    return list(labels), labels


def symbol_for(name):
    """ชื่อหุ้นของบริษัท: จากที่บันทึกไว้ หรือชื่อที่พิมพ์ตรงกับชื่อหุ้นใน SET"""
    if not name:
        return None
    saved = benchmark.symbols_of([name]).get(name)
    if saved:
        return saved
    try:
        return name.strip().upper() if name.strip().upper() in set_api.listed_companies() else None
    except SourceSkipped:
        return None


def _add_peers(base_symbol, key, limit):
    selected = list(st.session_state.get(key) or [])
    taken = set(benchmark.symbols_of(selected).values()) | {s.upper() for s in selected}
    by_symbol = {h["set_symbol"]: h["name"] for h in db.analyzed_companies() if h["set_symbol"]}
    try:
        peers = benchmark.suggest(base_symbol, exclude=taken, n=limit - len(selected))
    except SourceSkipped as e:
        st.session_state.peer_msg = f"หาไม่สำเร็จ: {e}"
        return
    st.session_state[key] = selected + [by_symbol.get(p, p) for p in peers]
    st.session_state.peer_msg = (f"เพิ่ม {', '.join(peers)} (ใหญ่สุดตามมูลค่าตลาดในหมวดเดียวกับ {base_symbol})"
                                 if peers else "ไม่มีบริษัทอื่นในหมวดให้เพิ่ม")


def peer_button(base, key="comp_input", limit=5):
    """ปุ่มเพิ่มบริษัทใหญ่สุดในหมวดธุรกิจเดียวกับ base (บริษัทเราหรือคู่แข่งรายแรก) เข้าช่องคู่แข่ง"""
    symbol = symbol_for(base)
    if not symbol:
        return
    full = len(st.session_state.get(key) or []) >= limit
    st.button(f"Add peers of {base}", icon=":material/group_add:", key="peer_btn",
              on_click=_add_peers, args=(symbol, key, limit), disabled=full, width="stretch",
              help="เลือกบริษัทจดทะเบียนที่ใหญ่สุดตามมูลค่าตลาดในหมวดธุรกิจ SET เดียวกัน "
                   "(ครั้งแรกดึงตัวเลขทั้งหมวดราว 10–30 วินาที ไม่ใช้ LLM)")
    if st.session_state.get("peer_msg"):
        st.caption(st.session_state.pop("peer_msg"))
