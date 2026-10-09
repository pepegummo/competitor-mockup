"""ขั้นตอนวิเคราะห์ทั้งหมด (ดึงข้อมูล → จัดหมวด → เทียบรอบก่อน → เขียนรายงาน) แยกจากหน้าเว็บ
เพื่อให้ทั้งแอป Streamlit และการรันอัตโนมัติ (monitor.py) ใช้ชุดเดียวกัน
log(text, kind): kind = "step" หัวข้อขั้น, "line" ผลย่อย, "note" หมายเหตุเล็ก, "status" ข้อความสถานะ"""
import pandas as pd

from core import analyze, benchmark, collect, db, impact, llm, monitor, process, profile
from core.sources import SourceSkipped, set_api
from ui.labels import CATEGORY_TH, FINANCIALS_KEY  # ไฟล์ข้อความล้วน ไม่มี streamlit

DEFAULT_OPTS = {"sources": ["google_news"], "fulltext": False, "review_limit": 20, "financials": False,
                "limit": 20, "internal": True}


def print_log(text, kind="line"):
    prefix = {"step": "\n== ", "line": "- ", "note": "  ", "status": "… "}.get(kind, "")
    print(prefix + text.replace("**", ""), flush=True)


def enabled_sources(row, picked):
    """แหล่งที่เลือกไว้ ลบแหล่งที่ปิดไว้เฉพาะบริษัทนี้"""
    return [k for k in picked if k not in row["disabled_sources"]]


def lookup_symbols(companies, log=print_log):
    """ข้อมูลประกอบของบริษัทที่ยังไม่เคยหา (1 LLM call รวมทุกบริษัท): ชื่อหุ้น SET (ตรวจกับรายชื่อหุ้นจริง)
    ชื่อที่สื่อใช้ (ใช้ค้นข่าว) และธุรกิจหลัก (ใช้ตัดข่าวที่ชื่อซ้ำแต่เป็นเรื่องอื่น)
    ชื่อหุ้นที่มีอยู่แล้ว (รวมที่ผู้ใช้แก้เอง) ไม่ถูกเขียนทับ"""
    rows = [r for r in db.get_companies(companies) if r["set_symbol"] is None or r["business"] is None]
    if not rows:
        return
    profiles = profile.suggest_profiles([r["name"] for r in rows])
    if not profiles:
        log("หาข้อมูลบริษัทอัตโนมัติไม่สำเร็จ ใส่ชื่อหุ้น/ชื่อเรียกเองได้ใน “แหล่งข้อมูลของแต่ละบริษัท”", "note")
        return
    found = []
    for r in rows:
        p = profiles.get(r["name"], {"set_symbol": "", "aliases": [], "business": ""})
        if r["set_symbol"] is None:
            db.set_company_profile(r["name"], p["set_symbol"], p["aliases"])
            found.append(f"{r['name']} → {p['set_symbol'] or 'ไม่อยู่ในตลาด'}")
        elif not r["aliases"] and p["aliases"]:
            db.set_company_profile(r["name"], r["set_symbol"], p["aliases"])
        db.set_company_business(r["name"], p["business"])
    if found:
        log("ชื่อหุ้น SET ที่ระบบหาให้: " + " · ".join(found) + " (ถ้าผิดแก้ได้ใน “แหล่งข้อมูลของแต่ละบริษัท”)")


def fetch_financials(ids, companies, log=print_log):
    """ดึงงบการเงินล่าสุดจาก SET ของบริษัทที่ใส่ชื่อหุ้นไว้ แล้วเก็บลง DB"""
    log("งบการเงิน (SET)", "step")
    for cid, row in zip(ids, db.get_companies(companies)):
        if FINANCIALS_KEY in row["disabled_sources"]:
            log(f"{row['name']} · ปิดงบการเงินไว้สำหรับบริษัทนี้", "note")
            continue
        if not row.get("set_symbol"):
            log(f"{row['name']} · ไม่มีงบ (ไม่อยู่ในตลาดหลักทรัพย์ฯ หรือยังไม่ได้ใส่ชื่อหุ้น)", "note")
            continue
        try:
            data = set_api.financials(row["set_symbol"])
        except SourceSkipped as e:
            log(f"{row['name']} · {e}", "note")
            continue
        db.save_financials(cid, row["set_symbol"], data)
        filed = data["latest"].get("filed_url") or ""
        log(f"**{row['name']}**: {row['set_symbol']} งบ {data['latest']['period']}"
            + (f" ([ไฟล์งบ]({filed}))" if filed else ""))


def fetch_sector(companies, log=print_log):
    """ตัวเลขของทุกบริษัทในหมวดธุรกิจเดียวกัน (ใช้จัดอันดับในหมวด) ดึงเฉพาะที่ยังไม่มีหรือเก่ากว่า 1 วัน"""
    symbols = benchmark.symbols_of(companies)
    if not symbols:
        return
    n = benchmark.refresh(symbols.values(), log=lambda m: log(m, "note"))
    groups = {f["name"]: len(f["df"]) for f in benchmark.frames(list(symbols.values())).values()}
    log("เทียบทั้งหมวด: " + " · ".join(f"{g} {k} บริษัท" for g, k in groups.items())
        + (f" (ดึงใหม่ {n})" if n else " (ใช้ข้อมูลที่เก็บไว้)"))


def run(companies, self_name=None, mode="compare", opts=None, focus=None, groups=None, watch_id=None,
        log=print_log):
    """companies = ทุกบริษัทที่วิเคราะห์ (รวมบริษัทเราและบริษัทในเครือ) ต้องมีใน DB แล้ว
    คืน {"report": row หรือ None, "empty": [...], "changes": [...], "self_name", "run_id", "error"}"""
    opts = {**DEFAULT_OPTS, **(opts or {})}
    groups = groups or {}
    focus_text = analyze.focus_label(focus, CATEGORY_TH)
    calls_before = llm.call_count
    ids = db.company_ids(companies)
    config = dict(companies=companies, self_name=self_name, mode=mode, opts=opts, focus=focus or {}, groups=groups)

    labels = [collect.SOURCES[k][1] for k in opts["sources"]]
    log(f"1/3 ดึงข้อมูล ({', '.join(labels)})"
        + (f" · ค้นเพิ่มเรื่อง: {', '.join(collect.topic_queries(focus))}" if focus_text else ""), "step")
    lookup_symbols(companies, log)  # ชื่อที่สื่อใช้และธุรกิจหลักใช้กับทุกแหล่ง ไม่ใช่แค่ SET
    if opts["fulltext"]:
        log("ดึงข้อมูลและเนื้อหาเต็ม (อาจใช้เวลาหลายนาที)...", "status")
    empty = []
    for cid, row in zip(ids, db.get_companies(companies)):
        name = row["name"]
        sources = enabled_sources(row, opts["sources"])
        stats, notes = collect.collect_company(cid, name, limit=opts["limit"], sources=sources,
                                               fulltext_on=opts["fulltext"], review_limit=opts["review_limit"],
                                               focus=focus)
        parts = [f"{label} {n} (ใหม่ {a})" for label, (n, a) in stats.items()]
        off = [collect.SOURCES[k][1] for k in opts["sources"] if k not in sources]
        log(f"**{name}**: " + (" · ".join(parts) or "ไม่มีแหล่งที่ใช้ได้")
            + (f" · ปิดไว้: {', '.join(off)}" if off else ""))
        for note in notes:
            log(f"{name} · {note}", "note")
        if sum(n for label, (n, a) in stats.items() if label != "รีวิวแอป") == 0:
            empty.append(name)
    if opts.get("financials"):
        fetch_financials(ids, companies, log)
        fetch_sector(companies, log)
        impact.refresh(benchmark.symbols_of(companies).values(), log=lambda m: log(m, "note"))

    log("2/3 จัดหมวดด้วย LLM", "step")
    saved, skipped, dropped = process.classify_pending(ids, on_progress=lambda m: log(m, "status"))
    log(f"จัดหมวดใหม่ {saved} รายการ" + ("" if saved else " (ทั้งหมดเคยจัดหมวดแล้ว)")
        + (f" · ตัดข่าวที่ชื่อตรงแต่ไม่ใช่เรื่องของบริษัทนั้น {dropped} รายการ" if dropped else ""))
    if skipped:
        log(f"ข้าม {skipped} ชุดที่ LLM ตอบรูปแบบไม่ถูก กดวิเคราะห์อีกครั้งเพื่อลองใหม่")

    all_df = analyze.load_df(ids)
    df, table_a, table_b, table_c = analyze.tables_from_df(analyze.apply_focus(all_df, focus))
    if focus_text:
        log(f"วิเคราะห์เฉพาะเรื่อง **{focus_text}**: {len(df)} รายการจาก {len(all_df)}")
    if table_a.empty:
        return {"report": None, "empty": empty, "changes": [], "self_name": self_name, "run_id": None,
                "error": "ไม่พบข่าวของบริษัทที่เลือก" + (" ในเรื่องที่สนใจ" if focus_text else "")}

    fins = db.financials_by_company(ids)
    fin = analyze.financial_table(fins) if fins else pd.DataFrame()
    events = impact.events(df, benchmark.symbols_of(companies)) if opts.get("financials") else pd.DataFrame()
    snapshot = monitor.snapshot(df, fin, impact.big_moves(events) if opts.get("financials") else None)
    changes = monitor.changes(companies, df, snapshot, db.previous_snapshots(companies), events)
    if not events.empty:
        log(f"ราคาหุ้นหลังข่าว: ขยับผิดปกติ {int(events['big'].sum())} ครั้งจาก {len(events)} วันที่มีข่าว")
    high = sum(c["level"] == "high" for c in changes)
    log(f"เทียบกับรอบก่อน: {len(changes)} เรื่อง" + (f" (สำคัญ {high})" if high else "")
        if changes else "เทียบกับรอบก่อน: ไม่มีอะไรเปลี่ยนหรือยังไม่มีรอบก่อนของบริษัทเหล่านี้")

    log("เขียนรายงาน...", "status")
    log("3/3 เขียนรายงาน", "step")
    report_mode = "phase1" if not self_name else ("phase3" if mode == "discover" else "phase2")
    reviews = analyze.review_table(df)
    internal = analyze.internal_table(companies) if opts.get("internal") else pd.DataFrame()
    gap = (analyze.gap_table(df, table_b, self_name, reviews, fin, members=groups, internal=internal)
           if self_name else None)
    if self_name and (gap is None or gap.empty):
        # ไม่มีข่าวของเราหรือของคู่แข่ง → เขียนรายงานกลาง ๆ แทน
        log(f"ไม่มีข่าวพอเทียบกับ {self_name} จึงเขียนรายงานแบบเทียบคู่แข่งแทน")
        self_name, report_mode = None, "phase1"
    sector = benchmark.table(benchmark.symbols_of(companies)) if opts.get("financials") else None
    analyze.write_report(table_a, table_b, table_c, self_name=self_name, gap=gap, mode=report_mode,
                         reviews=reviews, fin=fin, scope=focus_text or None, groups=groups,
                         changes=changes, internal=internal, sector=sector, price=events)
    report = db.latest_report(report_mode)
    # เวลาของรอบ = เวลาจบ ข่าวที่ดึงในรอบนี้จึงไม่ถูกนับเป็น "ใหม่" ในรอบถัดไป
    run_id = db.save_run(db.now(), config, snapshot, changes, report["id"], watch_id)
    log(f"วิเคราะห์เสร็จ · เรียก LLM {llm.call_count - calls_before} ครั้ง", "status")
    return {"report": report, "empty": empty, "changes": changes, "self_name": self_name, "run_id": run_id,
            "error": None}

