import json

import pandas as pd
import streamlit as st

from core import analyze, collect, db, discover, llm, process, profile
from core.sources import SourceSkipped, set_api
from ui import company_panel, results
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


def build_result(companies, report_row, self_name=None, mode="compare", focus=None, report_scope=None):
    """ข้อมูลของรอบวิเคราะห์ (กรองตามหัวข้อที่สนใจแล้ว) ตารางคิดใหม่ในหน้าผลลัพธ์ตามตัวกรอง"""
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
        report_scope=report_scope, fetched_at=db.last_fetched_at(ids),
    )


def restore_last_result():
    last = load_last_run()
    if not last:
        return None
    report = db.get_report(last.get("report_id"))
    if not report or not db.company_ids(last.get("companies", [])):
        return None
    return build_result(last["companies"], report, last.get("self_name"), last.get("mode", "compare"),
                        last.get("focus"), last.get("report_scope"))


def remember(res):
    save_last_run(companies=res["companies"], report_id=res["report_id"], self_name=res["self_name"],
                  mode=res["mode"], focus=res["focus"], report_scope=res["report_scope"])


def on_new_report(report_row, scope):
    """ผู้ใช้กดเขียนรายงานใหม่ตามตัวกรอง"""
    res = st.session_state.result
    res.update(report=report_row["content_md"], report_at=report_row["created_at"],
               report_id=report_row["id"], report_scope=scope)
    remember(res)


def run_pipeline(competitors, limit, self_name=None, origins=None, mode="compare", opts=None, focus=None):
    """self_name=None → Phase 1, มี self_name → Phase 2 (เรา vs คู่แข่ง)
    opts = {"sources", "fulltext", "review_limit", "financials"} จากแถบซ้าย
    focus = {"categories", "keywords"} หัวข้อที่สนใจ: ค้นข่าวเพิ่ม และวิเคราะห์เฉพาะเรื่องนั้น"""
    origins = origins or {}
    opts = opts or {"sources": ["google_news"], "fulltext": False, "review_limit": 20, "financials": False}
    companies = ([self_name] if self_name else []) + competitors
    focus_text = analyze.focus_label(focus, CATEGORY_TH)
    calls_before = llm.call_count
    with st.status("กำลังวิเคราะห์...", expanded=True) as status:
        ids = []
        for name in companies:
            if name == self_name:
                ids.append(db.upsert_company(name, role="self", origin="user"))
            else:
                ids.append(db.upsert_company(name, role="competitor", origin=origins.get(name, "user")))

        labels = [collect.SOURCES[k][1] for k in opts["sources"]]
        st.write(f"**1/3 ดึงข้อมูล** ({', '.join(labels)})"
                 + (f" · ค้นเพิ่มเรื่อง: {', '.join(collect.topic_queries(focus))}" if focus_text else ""))
        if "set_news" in opts["sources"] or opts.get("financials"):
            lookup_symbols(companies)
        if opts["fulltext"]:
            status.update(label="ดึงข้อมูลและเนื้อหาเต็ม (อาจใช้เวลาหลายนาที)...")
        empty = []
        for cid, row in zip(ids, db.get_companies(companies)):
            name = row["name"]
            sources = company_panel.enabled_sources(row, opts["sources"])
            stats, notes = collect.collect_company(cid, name, limit=limit, sources=sources,
                                                   fulltext_on=opts["fulltext"], review_limit=opts["review_limit"],
                                                   focus=focus)
            parts = [f"{label} {n} (ใหม่ {a})" for label, (n, a) in stats.items()]
            off = [collect.SOURCES[k][1] for k in opts["sources"] if k not in sources]
            st.write(f"- **{name}**: " + (" · ".join(parts) or "ไม่มีแหล่งที่ใช้ได้")
                     + (f" · ปิดไว้: {', '.join(off)}" if off else ""))
            for note in notes:
                st.caption(f"  {name} · {note}")
            if sum(n for label, (n, a) in stats.items() if label != "รีวิวแอป") == 0:
                empty.append(name)
        if opts.get("financials"):
            fetch_financials(ids, companies)

        st.write("**2/3 จัดหมวดด้วย LLM**")
        saved, skipped = process.classify_pending(ids, on_progress=lambda m: status.update(label=m))
        st.write(f"- จัดหมวดใหม่ {saved} รายการ" + ("" if saved else " (ทั้งหมดเคยจัดหมวดแล้ว)"))
        if skipped:
            st.write(f"- ข้าม {skipped} ชุดที่ LLM ตอบรูปแบบไม่ถูก กดวิเคราะห์อีกครั้งเพื่อลองใหม่")

        all_df = analyze.load_df(ids)
        df, table_a, table_b, table_c = analyze.tables_from_df(analyze.apply_focus(all_df, focus))
        if focus_text:
            st.write(f"- วิเคราะห์เฉพาะเรื่อง **{focus_text}**: {len(df)} รายการจาก {len(all_df)}")
        if table_a.empty:
            status.update(label="ไม่พบข่าวของบริษัทที่เลือก" + (" ในเรื่องที่สนใจ" if focus_text else ""),
                          state="error")
            return None, empty

        status.update(label="เขียนรายงาน...")
        st.write("**3/3 เขียนรายงาน**")
        report_mode = "phase1" if not self_name else ("phase3" if mode == "discover" else "phase2")
        reviews = analyze.review_table(df)
        fins = db.financials_by_company(ids)
        fin = analyze.financial_table(fins) if fins else pd.DataFrame()
        gap = analyze.gap_table(df, table_b, self_name, reviews, fin) if self_name else None
        if self_name and (gap is None or gap.empty):
            # ไม่มีข่าวของเราหรือของคู่แข่ง → เขียนรายงานกลาง ๆ แทน
            st.write(f"- ไม่มีข่าวพอเทียบกับ {self_name} จึงเขียนรายงานแบบเทียบคู่แข่งแทน")
            self_name, report_mode = None, "phase1"
        analyze.write_report(table_a, table_b, table_c, self_name=self_name, gap=gap, mode=report_mode,
                             reviews=reviews, fin=fin, scope=focus_text or None)
        report = db.latest_report(report_mode)
        status.update(label=f"วิเคราะห์เสร็จ · เรียก LLM {llm.call_count - calls_before} ครั้ง",
                      state="complete", expanded=False)

    res = build_result(companies, report, self_name, mode, focus)
    remember(res)
    return res, empty


def lookup_symbols(companies):
    """หาชื่อหุ้น SET ให้บริษัทที่ยังไม่เคยหา (1 LLM call ตรวจกับรายชื่อหุ้นจริง) แล้วแจ้งผลให้ผู้ใช้ตรวจ"""
    missing = [r["name"] for r in db.get_companies(companies) if r["set_symbol"] is None]
    if not missing:
        return
    profiles = profile.suggest_profiles(missing)
    if not profiles:
        st.caption("  หาชื่อหุ้น SET อัตโนมัติไม่สำเร็จ ใส่เองได้ใน “แหล่งข้อมูลของแต่ละบริษัท”")
        return
    for name in missing:
        p = profiles.get(name, {"set_symbol": "", "aliases": []})
        db.set_company_profile(name, p["set_symbol"], p["aliases"])
    st.write("- ชื่อหุ้น SET ที่ระบบหาให้: " + " · ".join(
        f"{n} → {profiles.get(n, {}).get('set_symbol') or 'ไม่อยู่ในตลาด'}" for n in missing)
        + " (ถ้าผิดแก้ได้ใน “แหล่งข้อมูลของแต่ละบริษัท”)")


def fetch_financials(ids, companies):
    """ดึงงบการเงินล่าสุดจาก SET ของบริษัทที่ใส่ชื่อหุ้นไว้ แล้วเก็บลง DB"""
    st.write("**งบการเงิน (SET)**")
    for cid, row in zip(ids, db.get_companies(companies)):
        if FINANCIALS_KEY in row["disabled_sources"]:
            st.caption(f"  {row['name']} · ปิดงบการเงินไว้สำหรับบริษัทนี้")
            continue
        if not row.get("set_symbol"):
            st.caption(f"  {row['name']} · ไม่มีงบ (ไม่อยู่ในตลาดหลักทรัพย์ฯ หรือยังไม่ได้ใส่ชื่อหุ้น)")
            continue
        try:
            data = set_api.financials(row["set_symbol"])
        except SourceSkipped as e:
            st.caption(f"  {row['name']} · {e}")
            continue
        db.save_financials(cid, row["set_symbol"], data)
        filed = data["latest"].get("filed_url") or ""
        st.write(f"- **{row['name']}**: {row['set_symbol']} งบ {data['latest']['period']}"
                 + (f" ([ไฟล์งบ]({filed}))" if filed else ""))


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
    st.session_state.self_input = last.get("self_name") or ""
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
        self_name = st.text_input("บริษัทของเรา", key="self_input", placeholder="เช่น AIS").strip() or None

    if mode == "discover":
        top_x = st.slider("จำนวนคู่แข่งที่ต้องการ", 3, 10, 5)
        industry = st.text_input("อุตสาหกรรม (ไม่บังคับ)", placeholder="เช่น โทรคมนาคม, ส่งอาหาร")
        country = st.text_input("ประเทศ", "ประเทศไทย") if adv else "ประเทศไทย"
    else:
        options = sorted(set(db.company_names()) | set(DEFAULT_COMPANIES) | set(st.session_state.comp_input),
                         key=str.lower)
        competitors = st.multiselect(
            "คู่แข่งที่ต้องการเทียบ", options, key="comp_input",
            accept_new_options=True, max_selections=5,
            placeholder="พิมพ์ชื่อบริษัทแล้วกด Enter",
            help="เลือก 2–5 ราย พิมพ์ชื่อบริษัทใหม่ได้",
        )
        competitors = [c for c in competitors if c != self_name]

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
            "review_limit": review_limit, "financials": FINANCIALS_KEY in picked}

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
        run = st.button("เริ่มวิเคราะห์", type="primary", disabled=bool(problems),
                        icon=":material/play_arrow:", width="stretch")
        st.caption(" และ ".join(problems) + " เพื่อเริ่ม" if problems
                   else "ใช้ LLM ประมาณ 1 ครั้งต่อข่าวใหม่ 10 ข่าว และอีก 1 ครั้งสำหรับรายงาน")

st.title("Competitor Compare")


def finish(new_res, empty):
    if empty:
        st.warning(f"ไม่พบข่าวของ: {', '.join(empty)} ลองตรวจตัวสะกดหรือใช้ชื่อที่สื่อใช้บ่อย")
    if new_res:
        results.reset_filters()  # ตัวกรองเดิมอาจไม่ตรงกับบริษัท/หมวดชุดใหม่
        st.session_state.result = new_res
    return st.session_state.result


if run:
    with friendly_errors():
        res = finish(*run_pipeline(competitors, limit, self_name=self_name, mode=mode, opts=opts, focus=focus))

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
company_panel.render(list(dict.fromkeys(upcoming)), panel_self, picked, adv)

if mode == "discover" and disc and disc["pending"]:
    panel = st.empty()
    with panel.container():
        confirmed, names, origins = confirm_panel(disc)
    if not confirmed:
        st.stop()
    panel.empty()
    with friendly_errors():
        res = finish(*run_pipeline(names, limit, self_name=disc["company"], origins=origins, mode="discover",
                                   opts=opts, focus=focus))
        disc["pending"] = False

if not res or (res["df"].empty and res["fin"].empty):
    empty_state()
    st.stop()

results.show(res, on_new_report)
