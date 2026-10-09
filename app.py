import json
import os
from datetime import datetime

import pandas as pd
import streamlit as st

from core import analyze, collect, db, discover, llm, pipeline
from ui import accuracy_panel, company_panel, company_picker, group_panel, internal_panel, results, watch_panel
from ui.common import friendly_errors
from ui.company_panel import ALL_SOURCES
from ui.labels import CATEGORY_TH, FINANCIALS_KEY, MODES, SENTIMENT_TH

DEFAULT_COMPANIES = ["AIS", "True", "NT"]
LAST_RUN = db.DATA_DIR / "last_run.json"
FOCUS_CATEGORIES = ["product_price", "promotion", "news_pr", "financial", "hr"]

st.set_page_config(page_title="Competitor Compare", page_icon="📊", layout="wide")
db.init_db()


# ---------- ข้อมูล ----------

def load_last_run():
    try:
        return json.loads(LAST_RUN.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def save_last_run(**data):
    LAST_RUN.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def build_result(companies, report_row, self_name=None, mode="compare", focus=None, report_scope=None, groups=None,
                 run_id=None, opts=None):
    """ข้อมูลของรอบวิเคราะห์ (กรองตามหัวข้อที่สนใจแล้ว) ตารางคิดใหม่ในหน้าผลลัพธ์ตามตัวกรอง
    groups = {บริษัทในเครือ: {parent, relation}} · run_id = รอบใน DB (มีสิ่งที่เปลี่ยนไปจากรอบก่อน)"""
    run = db.get_run(run_id) if run_id else None
    ids = db.company_ids(companies)
    df = analyze.apply_focus(analyze.load_df(ids), focus)
    if not df.empty:
        df["หมวด"] = df["category"].map(CATEGORY_TH)
        df["น้ำเสียง"] = df["sentiment"].map(SENTIMENT_TH)
        df["วันที่"] = df["published_dt"].dt.strftime("%Y-%m-%d")
        df["แหล่ง"] = df["source_type"].map(collect.SOURCE_TYPE_LABEL)
    fins = db.financials_by_company(ids)
    return dict(
        mode=mode, self_name=self_name, companies=companies, focus=focus or {},
        focus_label=analyze.focus_label(focus, CATEGORY_TH), df=df,
        fin=analyze.financial_table(fins) if fins else pd.DataFrame(), fin_raw=fins,
        report=report_row["content_md"], report_at=report_row["created_at"], report_id=report_row["id"],
        report_scope=report_scope, fetched_at=db.last_fetched_at(ids), groups=groups or {},
        run_id=run_id, run_at=run["started_at"] if run else None, changes=run["changes"] if run else None,
        opts=opts or (run["config"].get("opts") if run else None),
        llm=run["config"].get("llm") if run else None,
    )


def restore_last_result():
    last = load_last_run()
    if not last:
        return None
    report = db.get_report(last.get("report_id"))
    if not report or not db.company_ids(last.get("companies", [])):
        return None
    return build_result(last["companies"], report, last.get("self_name"), last.get("mode", "compare"),
                        last.get("focus"), last.get("report_scope"), last.get("groups"), last.get("run_id"),
                        last.get("opts"))


def remember(res):
    save_last_run(companies=res["companies"], report_id=res["report_id"], self_name=res["self_name"],
                  mode=res["mode"], focus=res["focus"], report_scope=res["report_scope"], groups=res["groups"],
                  run_id=res.get("run_id"), opts=res.get("opts"))


def open_run(run_id):
    """เปิดผลของรอบที่เคยรัน (เช่น รอบอัตโนมัติของชุดติดตาม)"""
    run = db.get_run(run_id)
    report = db.get_report(run["report_id"]) if run else None
    if not report:
        st.toast("ไม่พบผลของรอบนี้")
        return
    cfg = run["config"]
    res = build_result(cfg["companies"], report, cfg.get("self_name"), cfg.get("mode", "compare"), cfg.get("focus"),
                       groups=cfg.get("groups"), run_id=run_id)
    results.reset_filters()
    st.session_state.result = res
    remember(res)


def on_new_report(report_row, scope):
    """ผู้ใช้กดเขียนรายงานใหม่ตามตัวกรอง"""
    res = st.session_state.result
    res.update(report=report_row["content_md"], report_at=report_row["created_at"],
               report_id=report_row["id"], report_scope=scope)
    remember(res)


def add_group_members(top):
    """หาบริษัทในเครือของบริษัทหลัก (เฉพาะที่ยังไม่เคยหา) คืน (รายชื่อเรียงตามเครือ, groups)"""
    failed = group_panel.detect(top)
    if failed:
        st.caption(f"  หาบริษัทในเครือของ {', '.join(failed)} ไม่สำเร็จ วิเคราะห์ต่อโดยไม่รวม")
    group_panel.register(top)
    groups = group_panel.picked(top)
    ordered, lines = [], []
    for parent in top:
        members = [m for m, g in groups.items() if g["parent"] == parent]
        ordered += [parent] + members
        if members:
            lines.append(f"{parent} → {', '.join(members)}")
    st.write("- " + (" · ".join(lines) if lines else "ไม่มีบริษัทในเครือที่เลือกไว้"))
    return ordered, groups


def st_log(status):
    """แสดงความคืบหน้าของ pipeline ในกล่องสถานะ"""
    def log(text, kind="line"):
        if kind == "step":
            st.write(f"**{text}**")
        elif kind == "note":
            st.caption("  " + text)
        elif kind == "status":
            status.update(label=text)
        else:
            st.write("- " + text)
    return log


def register_companies(companies, self_name, origins=None):
    for name in companies:
        if name == self_name:
            db.upsert_company(name, role="self", origin="user")
        else:
            db.upsert_company(name, role="competitor", origin=(origins or {}).get(name, "user"))


def start_job(competitors, self_name=None, mode="compare", opts=None, focus=None, with_groups=False):
    """ขั้นที่ต้องโต้ตอบกับผู้ใช้ (บันทึกบริษัท หาบริษัทในเครือ) ทำในหน้าเว็บ แล้วส่งการวิเคราะห์ไปรันเบื้องหลัง
    (monitor.py --job) หน้าเว็บจึงไม่ค้าง ดูผลเดิมหรือไปหน้าอื่นระหว่างรอได้"""
    companies = ([self_name] if self_name else []) + competitors
    register_companies(companies, self_name)
    groups = {}
    if with_groups:
        with st.status("กำลังหาบริษัทในเครือ...", expanded=True) as status:
            pipeline.lookup_symbols(companies, st_log(status))
            companies, groups = add_group_members(companies)
            status.update(label="บริษัทในเครือ: " + (", ".join(groups) or "ไม่มีที่เลือกไว้"), state="complete",
                          expanded=False)
        for name, g in groups.items():
            db.upsert_company(name, role="self" if g["parent"] == self_name else "competitor", origin="group")
    job_id = db.create_job(dict(companies=companies, self_name=self_name, mode=mode, opts=opts, focus=focus,
                                groups=groups))
    watch_panel.start_background("--job", str(job_id))
    st.session_state.job_id = job_id


def _render_log(lines):
    for kind, text in lines:
        if kind == "step":
            st.write(f"**{text}**")
        elif kind == "note":
            st.caption("  " + text)
        elif kind in ("line", "warn"):
            st.write("- " + text)


@st.fragment(run_every=2)
def job_panel():
    """ความคืบหน้าของการวิเคราะห์เบื้องหลัง อ่านจาก DB ทุก 2 วินาที เสร็จแล้วเปิดผลให้เอง"""
    job = db.get_job(st.session_state.get("job_id"))
    if not job:
        st.session_state.pop("job_id", None)
        return
    lines = [tuple(line.split("|", 1)) for line in job["log"].splitlines() if "|" in line]
    if job["status"] == "running":
        seconds = int((datetime.now() - datetime.fromisoformat(job["started_at"])).total_seconds())
        label = next((t for k, t in reversed(lines) if k == "status"), "กำลังเริ่ม...")
        with st.status(f"{label} · {seconds} วินาที", expanded=True, state="running"):
            _render_log(lines)
            st.caption("รันเบื้องหลัง ดูผลเดิมด้านล่างหรือไปหน้าอื่นระหว่างรอได้")
            if seconds > 900 and st.button("เลิกรอ", key="job_cancel"):
                st.session_state.pop("job_id", None)
                st.rerun(scope="app")
        return
    st.session_state.pop("job_id", None)
    st.session_state.job_notes = [t for k, t in lines if k == "warn"]
    if job["status"] == "done" and job["run_id"]:
        open_run(job["run_id"])
    else:
        st.session_state.job_notes.append(job["error"] or "วิเคราะห์ไม่สำเร็จ")
    st.rerun(scope="app")


def run_pipeline(competitors, self_name=None, origins=None, mode="compare", opts=None, focus=None,
                 with_groups=False):
    """self_name=None → Phase 1, มี self_name → Phase 2 (เรา vs คู่แข่ง)
    opts = {"sources", "fulltext", "review_limit", "financials", "limit", "internal"} จากแถบซ้าย
    focus = {"categories", "keywords"} หัวข้อที่สนใจ: ค้นข่าวเพิ่ม และวิเคราะห์เฉพาะเรื่องนั้น
    with_groups = เพิ่มบริษัทในเครือที่ติ๊กไว้เป็นรายบริษัทแยก (ไม่นับเป็นคู่แข่งในตารางส่วนต่าง)"""
    origins = origins or {}
    companies = ([self_name] if self_name else []) + competitors
    calls_before = llm.call_count
    groups = {}
    with st.status("กำลังวิเคราะห์...", expanded=True) as status:
        log = st_log(status)
        register_companies(companies, self_name, origins)
        if with_groups:
            st.write("**บริษัทในเครือ**")
            pipeline.lookup_symbols(companies, log)  # ใช้ชื่อหุ้นกันบริษัทในเครือซ้ำกับบริษัทที่เลือกไว้แล้ว
            companies, groups = add_group_members(companies)
            for name, g in groups.items():
                db.upsert_company(name, role="self" if g["parent"] == self_name else "competitor", origin="group")
        out = pipeline.run(companies, self_name, mode, opts, focus, groups, log=log)
        if out["error"]:
            status.update(label=out["error"], state="error")
            return None, out["empty"]
        status.update(label=f"วิเคราะห์เสร็จ · เรียก LLM {llm.call_count - calls_before} ครั้ง",
                      state="complete", expanded=False)

    res = build_result(companies, out["report"], out["self_name"], mode, focus, groups=groups,
                       run_id=out["run_id"], opts=opts)
    remember(res)
    return res, out["empty"]


# ---------- ส่วนประกอบหน้า ----------

def empty_state():
    st.info("ทำตาม 3 ขั้นที่แถบด้านซ้าย แล้วกด **เริ่มวิเคราะห์**")
    cols = st.columns(3)
    steps = [
        ("1. ดึงข้อมูล", "ข่าว ข่าวแจ้งตลาด รีวิวแอป และงบการเงินล่าสุดจาก SET ของแต่ละบริษัท"),
        ("2. จัดหมวด", "ให้ LLM แยกหมวดและน้ำเสียงข่าว (บวก/กลาง/ลบ) ข่าวที่เคยจัดแล้วจะไม่ถูกส่งซ้ำ"),
        ("3. สรุปผล", "นับตัวเลขเปรียบเทียบ แล้วให้ LLM เขียนรายงานจากตัวเลขนั้น กรองดูผลได้ละเอียด"),
    ]
    for col, (title, text) in zip(cols, steps):
        with col.container(border=True):
            st.markdown(f"**{title}**")
            st.caption(text)


def confirm_panel(disc):
    """แสดงรายชื่อที่ระบบหาได้ ให้ผู้ใช้ติ๊กเลือก/เพิ่มเอง คืน (กดยืนยันไหม, รายชื่อ, origins)"""
    r = disc["result"]
    st.subheader(f"คู่แข่งที่พบสำหรับ {disc['company']}")
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


# ---------- หน้าเว็บ ----------

if "result" not in st.session_state:
    st.session_state.result = restore_last_result()
res = st.session_state.result
run = find = False

# ค่าเริ่มต้นของช่องกรอก ตั้งครั้งเดียวต่อ session (widget ใช้ key คงที่ ค่าจะไม่รีเซ็ตเองหลังวิเคราะห์)
if "mode_input" not in st.session_state:
    last = res or {}
    st.session_state.mode_input = last["mode"] if res and res["mode"] in MODES else "compare"
    st.session_state.self_input = last.get("self_name") or None
    st.session_state.comp_input = [c for c in (res["companies"] if res else DEFAULT_COMPANIES)
                                   if c != last.get("self_name")][:5]
    st.session_state.focus_cats = [c for c in last.get("focus", {}).get("categories", []) if c in FOCUS_CATEGORIES]
    st.session_state.focus_kw = ", ".join(last.get("focus", {}).get("keywords", []))

with st.sidebar:
    st.header("ตั้งค่าการวิเคราะห์")
    adv = st.toggle("ตัวเลือกละเอียด (นักวิเคราะห์)", key="adv",
                    help="เลือกแหล่งข้อมูลเอง ปิดแหล่งรายบริษัท จำนวนข่าว และดึงเนื้อหาเต็ม")

    st.subheader("① เทียบใครบ้าง", divider="gray")
    mode_keys = list(MODES)
    mode = st.radio("โหมด", mode_keys, format_func=lambda k: MODES[k][0],
                    captions=[MODES[k][1] for k in mode_keys], key="mode_input", label_visibility="collapsed")

    self_name = None
    if mode in ("self", "discover"):
        choices, labels = company_picker.options([st.session_state.self_input])
        self_name = st.selectbox(
            "บริษัทของเรา", choices, key="self_input", format_func=lambda n: labels.get(n, n),
            accept_new_options=True, placeholder="ค้นชื่อหุ้น/ชื่อบริษัท หรือพิมพ์ชื่อบริษัทนอกตลาด",
        )
        self_name = (self_name or "").strip() or None

    with_groups = st.toggle("รวมบริษัทในเครือ", key="with_groups", value=True,
                            help="เช่น CP → CPALL, CPF, CPAXT · PTT → PTTEP, OR, GC วิเคราะห์แยกเป็นรายบริษัท "
                                 "(ไม่นับเป็นคู่แข่ง) ตรวจความเป็นเจ้าของจากผู้ถือหุ้นใหญ่ใน SET")

    if mode == "discover":
        top_x = st.slider("จำนวนคู่แข่งที่ต้องการ", 3, 10, 5)
        industry = st.text_input("อุตสาหกรรม (ไม่บังคับ)", placeholder="เช่น ธนาคาร, โทรคมนาคม, ส่งอาหาร")
        country = st.text_input("ประเทศ", "ประเทศไทย") if adv else "ประเทศไทย"
    else:
        choices, labels = company_picker.options(st.session_state.comp_input)
        competitors = st.multiselect(
            "คู่แข่งที่ต้องการเทียบ", choices, key="comp_input", format_func=lambda n: labels.get(n, n),
            accept_new_options=True, max_selections=5,
            placeholder="ค้นชื่อหุ้น/ชื่อบริษัท เช่น KTB, แม็คกรุ๊ป",
            help="เลือก 2–5 ราย · บนสุดคือบริษัทที่เคยวิเคราะห์ ตามด้วยบริษัทใน SET และ mai ทั้งหมด "
                 "· บริษัทนอกตลาดพิมพ์ชื่อแล้วกด Enter",
        )
        competitors = [c for c in competitors if c != self_name]
        company_picker.peer_button(self_name or (competitors[0] if competitors else None))

    st.subheader("② สนใจเรื่องอะไร", divider="gray")
    focus_cats = st.pills("หมวด", FOCUS_CATEGORIES, format_func=CATEGORY_TH.get, selection_mode="multi",
                          key="focus_cats", help="เลือกแล้วจะค้นข่าวหมวดนั้นเพิ่ม และวิเคราะห์เฉพาะหมวดที่เลือก")
    focus_kw = st.text_input("คำค้นเฉพาะเรื่อง", key="focus_kw", placeholder="เช่น 5G, AI (คั่นด้วย ,)",
                             help="ค้นข่าวเพิ่มด้วย “ชื่อบริษัท + คำนี้” แล้ววิเคราะห์เฉพาะข่าว/รีวิวที่มีคำนี้ "
                                  "(งบการเงินไม่เปลี่ยน)")
    focus = {"categories": focus_cats or [], "keywords": [w.strip() for w in focus_kw.split(",") if w.strip()]}
    st.caption("ว่างไว้ = วิเคราะห์ทุกเรื่อง")

    st.subheader("③ ข้อมูลจากไหน", divider="gray")
    all_keys = list(ALL_SOURCES)
    if adv:
        picked = st.pills("แหล่งข้อมูล", all_keys, format_func=ALL_SOURCES.get, selection_mode="multi",
                          default=all_keys, key="src_pick")
        full = st.checkbox("ดึงเนื้อหาเต็มของข่าว", value=False, key="src_fulltext",
                           help="เปิดลิงก์ข่าวแต่ละข่าวเพื่ออ่านเนื้อหา ทำให้สรุปแม่นขึ้น แต่ช้าลงหลายนาที "
                                "และใช้ LLM มากขึ้น (ส่งทีละ 5 ข่าวแทน 10)")
        limit = st.slider("จำนวนข่าวต่อบริษัท ต่อแหล่ง", 10, 50, 20, step=5)
        review_limit = st.slider("จำนวนรีวิวต่อแอป", 10, 50, 20, step=5,
                                 help="รีวิวล่าสุดต่อแอปต่อสโตร์ ยิ่งมากยิ่งใช้ LLM มาก")
        st.caption("ปิดแหล่งเฉพาะบางบริษัทได้ใน “แหล่งข้อมูลของแต่ละบริษัท” ในหน้าหลัก")
    else:
        picked, full, limit, review_limit = all_keys, False, 20, 20
        st.caption("ใช้ทุกแหล่ง: ข่าว ข่าวแจ้งตลาด รีวิวแอป เว็บไซต์ และงบการเงินจาก SET · "
                   "เปิด “ตัวเลือกละเอียด” เพื่อเลือกเอง")
    picked = picked or []
    opts = {"sources": [k for k in picked if k != FINANCIALS_KEY], "fulltext": full,
            "review_limit": review_limit, "financials": FINANCIALS_KEY in picked, "limit": limit,
            "internal": st.session_state.get("internal_llm", True)}

    st.divider()
    if mode == "discover":
        find = st.button("หาคู่แข่ง", type="primary", disabled=not self_name,
                         icon=":material/search:", width="stretch")
        st.caption("ใช้ LLM 3 ครั้ง + ค้นข่าว แล้วให้คุณยืนยันรายชื่อก่อนวิเคราะห์"
                   if self_name else "กรอกชื่อบริษัทของเราเพื่อเริ่ม")
    else:
        problems = []
        if mode == "self" and not self_name:
            problems.append("กรอกชื่อบริษัทของเรา")
        if not 2 <= len(competitors) <= 5:
            problems.append("เลือกคู่แข่ง 2–5 ราย (ไม่นับบริษัทเรา)")
        if not opts["sources"]:
            problems.append("เลือกแหล่งข้อมูลอย่างน้อย 1 แหล่ง")
        if st.session_state.get("job_id"):
            problems.append("รอการวิเคราะห์ที่กำลังรันอยู่ให้เสร็จ")
        run = st.button("เริ่มวิเคราะห์", type="primary", disabled=bool(problems),
                        icon=":material/play_arrow:", width="stretch")
        st.caption(" และ ".join(problems) + " เพื่อเริ่ม" if problems
                   else "ใช้ LLM ประมาณ 1 ครั้งต่อข่าวใหม่ 10 ข่าว และอีก 1 ครั้งสำหรับรายงาน")

st.title("Competitor Compare")
if os.environ.get("CC_DEMO"):
    st.info(f"โหมดเดโม · ข้อมูลชุดตัวอย่างใน `{db.DATA_DIR.name}/` (ผลวิเคราะห์ คำถามตัวอย่าง ตัวเลข SET เก็บไว้แล้ว "
            "เปิดได้โดยไม่ต้องใช้เน็ตหรือเครื่อง LLM) · คำถามใหม่และการวิเคราะห์ใหม่ยังต้องใช้เน็ต",
            icon=":material/slideshow:")


def finish(new_res, empty):
    if empty:
        st.warning(f"ไม่พบข่าวของ: {', '.join(empty)} ลองตรวจตัวสะกดหรือใช้ชื่อที่สื่อใช้บ่อย")
    if new_res:
        results.reset_filters()  # ตัวกรองเดิมอาจไม่ตรงกับบริษัท/หมวดชุดใหม่
        st.session_state.result = new_res
    return st.session_state.result


if run:
    with friendly_errors():
        start_job(competitors, self_name=self_name, mode=mode, opts=opts, focus=focus, with_groups=with_groups)
if st.session_state.get("job_id"):
    job_panel()
for note in st.session_state.pop("job_notes", []):
    st.warning(note)
res = st.session_state.result

if find:
    with friendly_errors():
        with st.status(f"กำลังหาคู่แข่งของ {self_name}...", expanded=True) as status:
            found = discover.discover(self_name, top_x, country.strip() or "ประเทศไทย",
                                      industry.strip() or None, on_progress=st.write)
            status.update(label=found["message"], state="complete" if found["found"] else "error",
                          expanded=False)
        st.session_state.discovery = {"id": st.session_state.get("discovery", {}).get("id", 0) + 1,
                                      "company": self_name, "result": found, "pending": True}

# บริษัทที่จะวิเคราะห์ในรอบถัดไป ใช้กับการ์ดแหล่งข้อมูล
disc = st.session_state.get("discovery")
if mode == "discover":
    upcoming = [disc["company"]] + [c["name"] for c in disc["result"]["candidates"]] if disc else []
    panel_self = disc["company"] if disc else None
else:
    upcoming = ([self_name] if self_name else []) + competitors
    panel_self = self_name
upcoming = list(dict.fromkeys(upcoming))

# แท็บตั้งค่าแยกจากผล หน้าผลจึงไม่ถูกดันลงล่าง (ทุกแท็บรันทุกรอบ ค่าที่เลือกไว้ไม่หาย)
tab_res, tab_comp, tab_watch, tab_int, tab_acc = st.tabs(
    [":material/insights: ผลวิเคราะห์", ":material/tune: บริษัทและแหล่งข้อมูล",
     ":material/schedule: ติดตามอัตโนมัติ", ":material/upload_file: ข้อมูลภายใน", ":material/fact_check: ตรวจความแม่น"])
with tab_acc:
    accuracy_panel.render()
with tab_comp:
    members = {}
    if not upcoming:
        st.caption("เลือกบริษัทที่แถบซ้ายก่อน แล้วตั้งค่าแหล่งข้อมูลและบริษัทในเครือของแต่ละบริษัทได้ที่นี่")
    if with_groups:
        group_panel.render(upcoming)
        group_panel.register(upcoming)
        members = group_panel.picked(upcoming)
    company_panel.render(upcoming + list(members), panel_self, picked, adv, members)
with tab_int:
    internal_panel.render(panel_self or (res or {}).get("self_name"))
with tab_watch:
    if watch_panel.render(res, open_run):
        st.rerun()
res = st.session_state.result

with tab_res:
    if mode == "discover" and disc and disc["pending"]:
        panel = st.empty()
        with panel.container():
            confirmed, names, origins = confirm_panel(disc)
        if not confirmed:
            st.stop()
        panel.empty()
        with friendly_errors():
            res = finish(*run_pipeline(names, self_name=disc["company"], origins=origins, mode="discover",
                                       opts=opts, focus=focus, with_groups=with_groups))
            disc["pending"] = False

    if not res or (res["df"].empty and res["fin"].empty):
        empty_state()
        st.stop()

    results.show(res, on_new_report)
