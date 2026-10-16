"""หน้าวิเคราะห์ใหม่: ① เทียบใคร (บังคับ) ② สนใจเรื่องอะไร ③ ข้อมูลจากไหน (พับไว้ เปิดเมื่อต้องการ) → ปุ่มเดียว
กดแล้วส่งงานไปรันเบื้องหลังและพาไปหน้าภาพรวม · โหมดหาคู่แข่งให้ยืนยันรายชื่อในหน้านี้ก่อน"""
import streamlit as st

from core import discover
from ui import company_picker, nav, state
from ui.common import friendly_errors
from ui.company_panel import ALL_SOURCES
from ui.labels import CATEGORY_TH, MODES


def _step_who():
    """คืน (โหมด, บริษัทเรา, คู่แข่ง)"""
    with st.container(border=True):
        st.markdown("##### ① เทียบใครบ้าง (ต้องทำ)")
        keys = list(MODES)
        mode = st.segmented_control("รูปแบบ", keys, format_func=lambda k: MODES[k][0], key="mode_input",
                                    label_visibility="collapsed") or "compare"
        st.caption(MODES[mode][1])

        self_name, competitors = None, []
        if mode in ("self", "discover"):
            choices, labels = company_picker.options([st.session_state.self_input])
            self_name = st.selectbox(
                "บริษัทของเรา", choices, key="self_input", format_func=lambda n: labels.get(n, n),
                accept_new_options=True, placeholder="ค้นชื่อหุ้น/ชื่อบริษัท หรือพิมพ์ชื่อบริษัทนอกตลาด")
            self_name = (self_name or "").strip() or None

        if mode == "discover":
            c1, c2 = st.columns(2)
            c1.slider("จำนวนคู่แข่งที่ต้องการ", 3, 10, key="top_x")
            c2.text_input("อุตสาหกรรม (ไม่บังคับ)", key="industry", placeholder="เช่น ธนาคาร, โทรคมนาคม, ส่งอาหาร")
        else:
            choices, labels = company_picker.options(st.session_state.comp_input)
            competitors = st.multiselect(
                "คู่แข่ง (2–5 ราย)", choices, key="comp_input", format_func=lambda n: labels.get(n, n),
                accept_new_options=True, max_selections=5,
                placeholder="ค้นชื่อหุ้น/ชื่อบริษัท เช่น KTB, แม็คกรุ๊ป",
                help="บนสุดคือบริษัทที่เคยวิเคราะห์ ตามด้วยบริษัทใน SET และ mai ทั้งหมด "
                     "· บริษัทนอกตลาดพิมพ์ชื่อแล้วกด Enter")
            competitors = [c for c in competitors if c != self_name]
            company_picker.peer_button(self_name or (competitors[0] if competitors else None))

        st.toggle("รวมบริษัทในเครือ", key="with_groups",
                  help="เช่น CP → CPALL, CPF, CPAXT · PTT → PTTEP, OR, GC วิเคราะห์แยกเป็นรายบริษัท "
                       "(ไม่นับเป็นคู่แข่ง) ตรวจความเป็นเจ้าของจากผู้ถือหุ้นใหญ่ใน SET")
    return mode, self_name, competitors


def _step_focus():
    cats, kw = st.session_state.focus_cats or [], st.session_state.focus_kw.strip()
    chosen = [CATEGORY_TH[c] for c in cats] + ([kw] if kw else [])
    with st.expander("② สนใจเรื่องอะไร (ไม่บังคับ) · " + (", ".join(chosen) if chosen else "ทุกเรื่อง"),
                     icon=":material/filter_center_focus:"):
        st.pills("หมวด", state.FOCUS_CATEGORIES, format_func=CATEGORY_TH.get, selection_mode="multi",
                 key="focus_cats", help="เลือกแล้วจะค้นข่าวหมวดนั้นเพิ่ม และวิเคราะห์เฉพาะหมวดที่เลือก")
        st.text_input("คำค้นเฉพาะเรื่อง", key="focus_kw", placeholder="เช่น 5G, AI (คั่นด้วย ,)",
                      help="ค้นข่าวเพิ่มด้วย “ชื่อบริษัท + คำนี้” แล้ววิเคราะห์เฉพาะข่าว/รีวิวที่มีคำนี้ "
                           "(งบการเงินไม่เปลี่ยน)")
        st.caption("ว่างไว้ = วิเคราะห์ทุกเรื่อง")


def _step_sources(mode):
    picked = st.session_state.src_pick or []
    label = "ทุกแหล่ง" if len(picked) == len(ALL_SOURCES) else f"{len(picked)} จาก {len(ALL_SOURCES)} แหล่ง"
    with st.expander(f"③ ข้อมูลจากไหน (ไม่บังคับ) · {label}", icon=":material/database:"):
        st.pills("แหล่งข้อมูล", list(ALL_SOURCES), format_func=ALL_SOURCES.get, selection_mode="multi",
                 key="src_pick")
        st.checkbox("ดึงเนื้อหาเต็มของข่าว", key="src_fulltext",
                    help="เปิดลิงก์ข่าวแต่ละข่าวเพื่ออ่านเนื้อหา ทำให้สรุปแม่นขึ้น แต่ช้าลงหลายนาที "
                         "และใช้ LLM มากขึ้น (ส่งทีละ 5 ข่าวแทน 10)")
        c1, c2 = st.columns(2)
        c1.slider("จำนวนข่าวต่อบริษัท ต่อแหล่ง", 10, 50, step=5, key="src_limit")
        c2.slider("จำนวนรีวิวต่อแอป", 10, 50, step=5, key="src_review_limit",
                  help="รีวิวล่าสุดต่อแอปต่อสโตร์ ยิ่งมากยิ่งใช้ LLM มาก")
        if mode == "discover":
            st.text_input("ประเทศ", key="country")
        nav.link("companies", "ตรวจ/แก้แหล่งข้อมูลของแต่ละบริษัท (ชื่อแอป ชื่อหุ้น เว็บไซต์)")


def confirm_panel(disc):
    """แสดงรายชื่อที่ระบบหาได้ ให้ผู้ใช้ติ๊กเลือก/เพิ่มเอง คืน (กดยืนยันไหม, รายชื่อ, origins)"""
    r = disc["result"]
    st.markdown(f"##### คู่แข่งที่พบสำหรับ {disc['company']}")
    if not r["found"]:
        st.warning(r["message"])
        return False, [], {}
    st.caption(f"{r['message']} · ติ๊กเฉพาะรายที่ใช่ แล้วกดยืนยัน "
               "ถ้ารายชื่อผิด ผลวิเคราะห์ที่ตามมาจะผิดทั้งหมด")

    picked = []
    for i, c in enumerate(r["candidates"]):
        with st.container(border=True):
            check = st.checkbox(f"**{c['name']}**", value=not c["no_evidence"], key=f"cand_{disc['id']}_{i}")
            badges = [f":violet-badge[{s}]" if s == "LLM" else f":blue-badge[{s}]" for s in c["sources"]]
            if c["no_evidence"]:
                badges.append(":red-badge[ไม่พบหลักฐาน]")
            co = "20+" if c["co_mentions"] >= 20 else c["co_mentions"]
            st.markdown(" ".join(badges) + f" · ข่าวที่พูดถึงคู่กับ {disc['company']}: {co} ข่าว")
            if c["reason"]:
                st.caption(c["reason"])
            if c["evidence"]:
                st.markdown("\n".join(f"- [{e['title']}]({e['url']})" for e in c["evidence"]))
            if check:
                picked.append(c["name"])

    extra = st.text_input("เพิ่มคู่แข่งเอง (คั่นด้วย ,)", key=f"extra_{disc['id']}", placeholder="เช่น dtac, Jasmine")
    typed = [n.strip() for n in extra.split(",") if n.strip() and n.strip() not in picked]
    names = picked + typed
    too_many = len(names) > 10
    ok = st.button(f"ยืนยันและวิเคราะห์ ({len(names)} ราย)", type="primary",
                   disabled=not names or too_many, icon=":material/check:")
    if too_many:
        st.caption("เลือกได้สูงสุด 10 ราย")
    origins = {n: "discovered" for n in picked} | {n: "user" for n in typed}
    return ok, names, origins


def _discover_flow(self_name):
    find = st.button("หาคู่แข่ง", type="primary", disabled=not self_name or state.job_running(),
                     icon=":material/search:")
    st.caption("ใช้ LLM 3 ครั้ง + ค้นข่าว แล้วให้คุณยืนยันรายชื่อก่อนวิเคราะห์"
               if self_name else "กรอกชื่อบริษัทของเราเพื่อเริ่ม")
    f = state.form()
    if find:
        with friendly_errors():
            with st.status(f"กำลังหาคู่แข่งของ {self_name}...", expanded=True) as status:
                found = discover.discover(self_name, f["top_x"], (f["country"] or "").strip() or "ประเทศไทย",
                                          (f["industry"] or "").strip() or None, on_progress=st.write)
                status.update(label=found["message"], state="complete" if found["found"] else "error",
                              expanded=False)
            st.session_state.discovery = {"id": st.session_state.get("discovery", {}).get("id", 0) + 1,
                                          "company": self_name, "result": found, "pending": True}
    disc = st.session_state.get("discovery")
    if not (disc and disc["pending"]):
        return
    confirmed, names, origins = confirm_panel(disc)
    if confirmed:
        with friendly_errors():
            state.finish(*state.run_pipeline(names, self_name=disc["company"], origins=origins, mode="discover",
                                             opts=state.make_opts(f), focus=state.make_focus(f),
                                             with_groups=f["with_groups"]))
            disc["pending"] = False
            nav.go("overview")


def _start(mode, self_name, competitors):
    f = state.form()
    opts = state.make_opts(f)
    problems = []
    if mode == "self" and not self_name:
        problems.append("เลือกบริษัทของเรา")
    if not 2 <= len(competitors) <= 5:
        problems.append("เลือกคู่แข่ง 2–5 ราย (ไม่นับบริษัทเรา)")
    if not opts["sources"]:
        problems.append("เลือกแหล่งข้อมูลอย่างน้อย 1 แหล่ง")
    if state.job_running():
        problems.append("รอการวิเคราะห์ที่กำลังรันอยู่ให้เสร็จ")

    n = len(competitors) + (1 if self_name else 0)
    with st.container(border=True):
        c1, c2 = st.columns([3, 1.2], vertical_alignment="center")
        if problems:
            c1.markdown(":orange[:material/error_outline:] " + " · ".join(problems))
        else:
            c1.markdown(f"จะวิเคราะห์ **{n} บริษัท** จาก **{len(f['src_pick'])} แหล่ง**"
                        + (" · ดึงเนื้อหาเต็ม" if opts["fulltext"] else ""))
            c1.caption("รันเบื้องหลัง ปกติ 1–3 นาที" + (" (ดึงเนื้อหาเต็มนานขึ้นหลายนาที)" if opts["fulltext"] else "")
                       + " · ใช้ LLM ประมาณ 1 ครั้งต่อข่าวใหม่ 10 ข่าว + 1 ครั้งสำหรับรายงาน")
        go = c2.button("เริ่มวิเคราะห์", type="primary", disabled=bool(problems),
                       icon=":material/play_arrow:", width="stretch")
    if go:
        with friendly_errors():
            state.start_job(competitors, self_name=self_name, mode=mode, opts=opts, focus=state.make_focus(f),
                            with_groups=f["with_groups"])
            nav.go("overview")


def render():
    state.restore_form()
    st.title("วิเคราะห์ใหม่")
    st.caption("3 ขั้น: ① เลือกบริษัท (ต้องทำ) → ② เลือกเรื่องที่สนใจ (ไม่บังคับ) → ③ เลือกแหล่งข้อมูล (ไม่บังคับ) "
               "แล้วกด “เริ่มวิเคราะห์” ด้านล่าง · ดูรายละเอียดที่หน้า “วิธีใช้”")
    mode, self_name, competitors = _step_who()
    _step_focus()
    _step_sources(mode)
    state.save_form()  # ก่อนกดปุ่ม: nav.go() หยุดสคริปต์ทันที
    if mode == "discover":
        _discover_flow(self_name)
    else:
        _start(mode, self_name, competitors)
