"""สถานะที่ทุกหน้าใช้ร่วมกัน: ผลวิเคราะห์ที่เปิดอยู่ ค่าในฟอร์มวิเคราะห์ใหม่ (จำข้ามหน้า) และงานวิเคราะห์เบื้องหลัง
ย้ายมาจาก app.py เดิม logic การวิเคราะห์ไม่เปลี่ยน"""
import json
from datetime import datetime

import pandas as pd
import streamlit as st

from core import analyze, collect, db, llm, pipeline
from ui import group_panel, watch_panel
from ui.company_panel import ALL_SOURCES
from ui.labels import CATEGORY_TH, FINANCIALS_KEY, MODES, SENTIMENT_TH

DEFAULT_COMPANIES = ["AIS", "True", "NT"]
LAST_RUN = db.DATA_DIR / "last_run.json"
FOCUS_CATEGORIES = ["product_price", "promotion", "news_pr", "financial", "hr"]


# ---------- ผลวิเคราะห์ที่เปิดอยู่ ----------

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


def set_result(res):
    from ui import results  # results import state ไม่ได้ (วน) จึง import ตอนใช้
    results.reset_filters()  # ตัวกรองเดิมอาจไม่ตรงกับบริษัท/หมวดชุดใหม่
    st.session_state.result = res
    remember(res)


def open_run(run_id):
    """เปิดผลของรอบที่เคยรัน (เช่น รอบอัตโนมัติของชุดติดตาม) คืน True ถ้าเปิดได้"""
    run = db.get_run(run_id)
    report = db.get_report(run["report_id"]) if run else None
    if not report:
        st.toast("ไม่พบผลของรอบนี้")
        return False
    cfg = run["config"]
    set_result(build_result(cfg["companies"], report, cfg.get("self_name"), cfg.get("mode", "compare"),
                            cfg.get("focus"), groups=cfg.get("groups"), run_id=run_id))
    return True


def on_new_report(report_row, scope):
    """ผู้ใช้กดเขียนรายงานใหม่ตามตัวกรอง"""
    res = st.session_state.result
    res.update(report=report_row["content_md"], report_at=report_row["created_at"],
               report_id=report_row["id"], report_scope=scope)
    remember(res)


def result_title(res):
    top = [c for c in res["companies"] if c not in res.get("groups", {})]
    if res.get("self_name"):
        return f"{res['self_name']} vs " + ", ".join(c for c in top if c != res["self_name"])
    return " · ".join(top)


# ---------- ค่าในฟอร์มวิเคราะห์ใหม่ (จำข้ามหน้า) ----------
# Streamlit ลบ state ของ widget ที่ไม่ได้แสดงในรอบนั้น (เช่น ตอนอยู่หน้าอื่น) จึงเก็บสำเนาไว้ใน "setup"
# แล้วคืนค่าให้ widget ทุกครั้งที่เปิดหน้าวิเคราะห์ใหม่

FORM_KEYS = ("mode_input", "self_input", "comp_input", "with_groups", "focus_cats", "focus_kw", "src_pick",
             "src_fulltext", "src_limit", "src_review_limit", "top_x", "industry", "country")


def _initial_form():
    last = st.session_state.get("result") or {}
    self_name = last.get("self_name")
    return {
        "mode_input": last["mode"] if last and last["mode"] in MODES else "compare",
        "self_input": self_name or None,
        "comp_input": [c for c in (last["companies"] if last else DEFAULT_COMPANIES)
                       if c != self_name and c not in last.get("groups", {})][:5],
        "with_groups": True,
        "focus_cats": [c for c in last.get("focus", {}).get("categories", []) if c in FOCUS_CATEGORIES],
        "focus_kw": ", ".join(last.get("focus", {}).get("keywords", [])),
        "src_pick": list(ALL_SOURCES), "src_fulltext": False, "src_limit": 20, "src_review_limit": 20,
        "top_x": 5, "industry": "", "country": "ประเทศไทย",
    }


def form():
    """ค่าล่าสุดของฟอร์ม (dict) ใช้ได้ทุกหน้า"""
    if "setup" not in st.session_state:
        st.session_state.setup = _initial_form()
    return st.session_state.setup


def restore_form():
    """เรียกก่อนสร้าง widget ในหน้าวิเคราะห์ใหม่"""
    for k, v in form().items():
        if k not in st.session_state:
            st.session_state[k] = v


def save_form():
    """เรียกท้ายหน้าวิเคราะห์ใหม่"""
    form().update({k: st.session_state[k] for k in FORM_KEYS if k in st.session_state})


def internal_llm_on():
    """สวิตช์ "ให้ LLM ใช้ข้อมูลภายใน" ในหน้าข้อมูลภายใน (จำข้ามหน้า ค่าเริ่มต้นเปิด)"""
    return st.session_state.get("internal_llm_on", True)


def make_opts(f=None):
    """ตัวเลือกการดึงข้อมูลจากค่าในฟอร์ม → opts ของ pipeline"""
    f = f or form()
    picked = f.get("src_pick") or []
    return {"sources": [k for k in picked if k != FINANCIALS_KEY], "fulltext": bool(f.get("src_fulltext")),
            "review_limit": f.get("src_review_limit", 20), "financials": FINANCIALS_KEY in picked,
            "limit": f.get("src_limit", 20), "internal": internal_llm_on()}


def make_focus(f=None):
    f = f or form()
    return {"categories": f.get("focus_cats") or [],
            "keywords": [w.strip() for w in (f.get("focus_kw") or "").split(",") if w.strip()]}


def upcoming():
    """(บริษัทที่จะวิเคราะห์รอบถัดไป, บริษัทเรา) ใช้กับหน้าบริษัทและแหล่งข้อมูล"""
    f = form()
    disc = st.session_state.get("discovery")
    if f["mode_input"] == "discover":
        names = [disc["company"]] + [c["name"] for c in disc["result"]["candidates"]] if disc else []
        return list(dict.fromkeys(names)), disc["company"] if disc else None
    self_name = (f.get("self_input") or "").strip() or None if f["mode_input"] != "compare" else None
    return list(dict.fromkeys(([self_name] if self_name else []) + list(f.get("comp_input") or []))), self_name


# ---------- เริ่มวิเคราะห์ ----------

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


def job_running():
    return bool(st.session_state.get("job_id"))


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


def run_pipeline(competitors, self_name=None, origins=None, mode="compare", opts=None, focus=None,
                 with_groups=False):
    """วิเคราะห์ในหน้าเว็บ (ใช้กับโหมดหาคู่แข่งหลังผู้ใช้ยืนยันรายชื่อ) คืน (ผล, บริษัทที่ไม่พบข่าว)"""
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
    return res, out["empty"]


def finish(new_res, empty):
    """เปิดผลใหม่ · คำเตือนเก็บไว้แสดงในหน้าภาพรวม (หลังเปลี่ยนหน้า)"""
    if empty:
        st.session_state.setdefault("job_notes", []).append(
            f"ไม่พบข่าวของ: {', '.join(empty)} ลองตรวจตัวสะกดหรือใช้ชื่อที่สื่อใช้บ่อย")
    if new_res:
        set_result(new_res)


# ---------- งานเบื้องหลัง ----------

def _job_lines(job):
    return [tuple(line.split("|", 1)) for line in job["log"].splitlines() if "|" in line]


def _render_log(lines):
    for kind, text in lines:
        if kind == "step":
            st.write(f"**{text}**")
        elif kind == "note":
            st.caption("  " + text)
        elif kind in ("line", "warn"):
            st.write("- " + text)


@st.fragment(run_every=2)
def job_watch():
    """อยู่ใน sidebar ทุกหน้า: บอกว่ากำลังวิเคราะห์ และเปิดผลให้เองเมื่อเสร็จ (ไม่ว่าผู้ใช้อยู่หน้าไหน)"""
    job = db.get_job(st.session_state.get("job_id"))
    if not job:
        st.session_state.pop("job_id", None)
        return
    if job["status"] == "running":
        seconds = int((datetime.now() - datetime.fromisoformat(job["started_at"])).total_seconds())
        label = next((t for k, t in reversed(_job_lines(job)) if k == "status"), "กำลังเริ่ม...")
        st.info(f"**กำลังวิเคราะห์** · {seconds} วินาที  \n{label}", icon=":material/hourglass_top:")
        return
    st.session_state.pop("job_id", None)
    lines = _job_lines(job)
    st.session_state.job_notes = [t for k, t in lines if k == "warn"]
    if job["status"] == "done" and job["run_id"] and open_run(job["run_id"]):
        st.session_state.toast = "วิเคราะห์เสร็จแล้ว เปิดผลในหน้าภาพรวม"
    else:
        st.session_state.job_notes.append(job["error"] or "วิเคราะห์ไม่สำเร็จ")
    st.rerun(scope="app")


@st.fragment(run_every=2)
def job_progress():
    """รายละเอียดความคืบหน้าในหน้าภาพรวม (เมื่อเสร็จ job_watch ใน sidebar จะเปิดผลให้)"""
    job = db.get_job(st.session_state.get("job_id"))
    if not job or job["status"] != "running":
        return
    seconds = int((datetime.now() - datetime.fromisoformat(job["started_at"])).total_seconds())
    lines = _job_lines(job)
    label = next((t for k, t in reversed(lines) if k == "status"), "กำลังเริ่ม...")
    with st.status(f"{label} · {seconds} วินาที", expanded=True, state="running"):
        _render_log(lines)
        st.caption("รันเบื้องหลัง ไปหน้าอื่นระหว่างรอได้ เสร็จแล้วระบบเปิดผลให้เอง")
        if seconds > 900 and st.button("เลิกรอ", key="job_cancel"):
            st.session_state.pop("job_id", None)
            st.rerun(scope="app")
