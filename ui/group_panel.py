"""บริษัทในเครือ: หาบริษัทลูก/บริษัทร่วมของแต่ละบริษัท ให้ผู้ใช้ติ๊กเลือก แล้ววิเคราะห์แยกเป็นรายบริษัท
ค่าเริ่มต้นติ๊กเฉพาะรายที่ยืนยันได้จากผู้ถือหุ้นใหญ่ใน SET ผลการหาเก็บใน DB ไม่ถาม LLM ซ้ำ"""
import streamlit as st

from core import db, group
from ui.common import friendly_errors

MAX_COMPANIES = 20  # รวมบริษัทหลักและบริษัทในเครือ (มากกว่านี้ใช้เวลาและ LLM มากเกินไปสำหรับ mock-up)


def _key(parent, member):
    return f"grp_{parent}_{member}"


def detect(names, refresh=False):
    """หาบริษัทในเครือของชื่อที่ยังไม่เคยหา (1 LLM call รวมทุกชื่อ) คืนรายชื่อที่หาไม่สำเร็จ"""
    todo = list(names) if refresh else [n for n in names if n not in db.get_groups(names)]
    if not todo:
        return []
    found = group.find_groups(todo)
    for name in todo:
        if name in found:
            db.save_group(name, found[name])
            for m in found[name]["members"]:  # ติ๊กใหม่ตามผลล่าสุด
                st.session_state.pop(_key(name, m["name"]), None)
    return [n for n in todo if n not in found]


def candidates(names):
    """[(parent, member, สถานะ)] เรียงตาม names · สถานะ "dup" = เป็นบริษัทที่อยู่ในรายชื่อแล้ว/ซ้ำกับเครืออื่น"""
    groups = db.get_groups(names)
    rows = {r["name"]: r for r in db.get_companies(names)}
    taken_names = {n.casefold() for n in names}
    taken_symbols = {r["set_symbol"] for r in rows.values() if r.get("set_symbol")}
    out = []
    for parent in names:
        for m in (groups.get(parent) or {}).get("members", []):
            dup = m["name"].casefold() in taken_names or (m["set_symbol"] and m["set_symbol"] in taken_symbols)
            out.append((parent, m, "dup" if dup else "ok"))
            if not dup:
                taken_names.add(m["name"].casefold())
                if m["set_symbol"]:
                    taken_symbols.add(m["set_symbol"])
    return out


def picked(names):
    """{ชื่อบริษัทในเครือ: {parent, relation}} ที่ติ๊กไว้ (ค่าเริ่มต้น = ยืนยันได้จากผู้ถือหุ้น)"""
    out = {}
    for parent, m, status in candidates(names):
        if status == "ok" and st.session_state.get(_key(parent, m["name"]), m["verified"] is True):
            out[m["name"]] = {"parent": parent, "relation": m["relation"]}
    room = max(MAX_COMPANIES - len(names), 0)
    return dict(list(out.items())[:room])


def register(names):
    """สร้างแถวบริษัทในเครือที่ติ๊กไว้และยังไม่มีใน DB พร้อมชื่อหุ้นและชื่อเรียกจากผลการหา (ไม่ทับค่าที่ผู้ใช้แก้ไว้)
    รายที่ไม่ได้ติ๊กไม่สร้างแถว (เดิมสร้างทุกรายที่แสดง ทำให้มีแถวว่างค้างในรายชื่อบริษัท)"""
    chosen = picked(names)
    for parent, m, status in candidates(names):
        if m["name"] in chosen and not db.company_ids([m["name"]]):
            db.update_company_sources(m["name"], m["aliases"], set_symbol=m["set_symbol"])
            db.set_company_profile(m["name"], m["set_symbol"], m["aliases"])
            if m.get("business"):
                db.set_company_business(m["name"], m["business"])


def render(names):
    if not names:
        return
    groups = db.get_groups(names)
    pending = [n for n in names if n not in groups]
    chosen = picked(names)
    title = "บริษัทในเครือ" + (f" · เลือก {len(chosen)} บริษัท" if chosen else "")
    with st.expander(title, icon=":material/account_tree:", expanded=bool(pending) or not chosen):
        c1, c2 = st.columns([1.4, 3])
        label = "หาบริษัทในเครือ" if pending else "หาใหม่"
        if c1.button(label, icon=":material/travel_explore:", key="grp_find",
                     help="ใช้ LLM 1 ครั้ง แล้วตรวจผู้ถือหุ้นใหญ่ของแต่ละหุ้นกับ SET"):
            with friendly_errors(), st.spinner("กำลังหาบริษัทในเครือ..."):
                failed = detect(names, refresh=not pending)
                if failed:
                    st.warning(f"หาไม่สำเร็จ: {', '.join(failed)} ลองกดอีกครั้ง")
                else:
                    st.rerun()
        c2.caption("บริษัทในเครือที่ติ๊กจะถูกวิเคราะห์แยกเป็นรายบริษัท แต่ไม่นับเป็นคู่แข่งในตารางส่วนต่าง "
                   + (f"· ยังไม่ได้หา: {', '.join(pending)} (ระบบจะหาให้ตอนกดวิเคราะห์)" if pending else ""))

        by_parent = {}
        for parent, m, status in candidates(names):
            by_parent.setdefault(parent, []).append((m, status))
        for parent in names:
            if parent in pending:
                continue
            members = by_parent.get(parent, [])
            st.markdown(f"**{parent}**" + ("" if members else " :gray[· ไม่พบบริษัทในเครือที่ควรเทียบแยก]"))
            for m, status in members:
                badge = {True: ":green-badge[ยืนยันจาก SET]", False: ":red-badge[ไม่ใช่ผู้ถือหุ้นใหญ่]",
                         None: ":gray-badge[ตรวจไม่ได้]"}[m["verified"]]
                text = (f"{m['name']}" + (f" ({m['set_symbol']})" if m["set_symbol"] else "")
                        + f" · {group.RELATION_TH[m['relation']]}" + (f" · {m['business']}" if m["business"] else ""))
                if status == "dup":
                    st.caption(f"{text} · อยู่ในรายชื่อแล้ว")
                    continue
                st.checkbox(f"{text}  {badge}", value=m["verified"] is True, key=_key(parent, m["name"]),
                            help=m["evidence"])
        if len(names) + len(picked(names)) >= MAX_COMPANIES:
            st.caption(f"วิเคราะห์ได้สูงสุด {MAX_COMPANIES} บริษัทต่อรอบ รายที่เกินจะไม่ถูกรวม")
