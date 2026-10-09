"""รันชุดติดตามทั้งหมดโดยไม่ต้องเปิดแอป (Windows Task Scheduler เรียกไฟล์นี้ตามเวลาที่ตั้งในแอป)
    python monitor.py            รันทุกชุด
    python monitor.py --id 3     รันเฉพาะชุดที่ 3
    python monitor.py --test-alert  ทดสอบส่งแจ้งเตือน
    python monitor.py --job 7    รันงานวิเคราะห์ที่แอปสร้างไว้ (ตาราง jobs) แบบเบื้องหลัง หน้าเว็บอ่านความคืบหน้าจาก DB
ผลแต่ละรอบเก็บใน data/app.db (ตาราง runs) เปิดดูในแอปได้ · บันทึกการทำงานอยู่ที่ data/monitor.log"""
import argparse
import os
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent
os.chdir(ROOT)  # Task Scheduler เริ่มที่ System32
sys.path.insert(0, str(ROOT))

from core import db, monitor, pipeline  # noqa: E402

LOG = db.DATA_DIR / "monitor.log"


def log(text, kind="line"):
    if kind == "status":
        return
    prefix = {"step": "\n== ", "line": "- ", "note": "  "}.get(kind, "")
    line = prefix + text.replace("**", "")
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")
    try:
        print(line, flush=True)
    except (UnicodeEncodeError, OSError):
        pass  # pythonw ไม่มีหน้าจอ / console ไม่รองรับภาษาไทย


def run_watch(w):
    cfg = w["config"]
    log(f"[{db.now()}] ชุด {w['id']}: {w['name']} ({', '.join(cfg['companies'])})", "step")
    out = pipeline.run(cfg["companies"], cfg.get("self_name"), cfg.get("mode", "compare"), cfg.get("opts"),
                       cfg.get("focus"), cfg.get("groups"), watch_id=w["id"], log=log)
    if out["error"]:
        log(out["error"])
        return
    text = monitor.alert_text(f"{w['name']} · {db.now()[:16].replace('T', ' ')}", out["changes"])
    if text and monitor.webhook_url():
        ok, msg = monitor.send_alert(text)
        log(f"แจ้งเตือน: {msg}")
    elif text:
        log("มีเรื่องสำคัญ แต่ยังไม่ได้ตั้ง ALERT_WEBHOOK_URL (ดูได้ในแอป)")
    else:
        log("ไม่มีเรื่องสำคัญ ไม่ส่งแจ้งเตือน")


def run_job(job_id):
    """งานที่ปุ่ม “เริ่มวิเคราะห์” ในแอปสร้างไว้: บันทึกความคืบหน้าลง jobs.log ให้หน้าเว็บแสดงระหว่างรัน"""
    job = db.get_job(job_id)
    if not job:
        return
    cfg = job["config"]

    def job_log(text, kind="line"):
        db.append_job_log(job_id, f"{kind}|{text}")

    try:
        out = pipeline.run(cfg["companies"], cfg.get("self_name"), cfg.get("mode", "compare"), cfg.get("opts"),
                           cfg.get("focus"), cfg.get("groups"), log=job_log)
        if out["empty"]:
            job_log(f"ไม่พบข่าวของ: {', '.join(out['empty'])} ลองตรวจตัวสะกดหรือใช้ชื่อที่สื่อใช้บ่อย", "warn")
        db.finish_job(job_id, out["run_id"], out["error"])
    except Exception as e:  # ให้หน้าเว็บรู้ว่าพัง แทนที่จะรอไปเรื่อย ๆ
        log(traceback.format_exc())
        db.finish_job(job_id, error=f"{type(e).__name__}: {e}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--id", type=int)
    parser.add_argument("--test-alert", action="store_true")
    parser.add_argument("--job", type=int)
    args = parser.parse_args()
    db.init_db()
    if args.job:
        run_job(args.job)
        return
    if args.test_alert:
        print(monitor.send_alert("📊 Competitor Compare: ทดสอบการแจ้งเตือน")[1])
        return
    watches = [w for w in db.watchlists() if args.id is None or w["id"] == args.id]
    if not watches:
        log(f"ไม่พบชุดติดตามที่ {args.id}" if args.id else "ยังไม่มีชุดติดตาม บันทึกได้จาก “ติดตามอัตโนมัติ” ในแอป")
    for w in watches:
        try:
            run_watch(w)
        except Exception:  # ชุดหนึ่งพังไม่ให้ชุดอื่นหยุด
            log(traceback.format_exc())


if __name__ == "__main__":
    main()
