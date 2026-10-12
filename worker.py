"""container worker ใน docker: แทน subprocess + Windows Task Scheduler ของการรันบนเครื่อง
    - วนทุก 5 วินาที หยิบงานในตาราง jobs ที่หน้าเว็บสร้างไว้ (status = 'queued') มารันทีละงาน
    - ถึงเวลา MONITOR_AT (เช่น 07:00 ตาม TZ) รันทุกชุดติดตามวันละครั้ง
    python worker.py"""
import os
import time
import traceback
from datetime import date, datetime

import monitor
from core import db

POLL_SECONDS = 5
LAST_DAILY = db.DATA_DIR / "last_daily_run.txt"  # วันที่รันรายวันล่าสุด: รีสตาร์ทแล้วไม่รันซ้ำในวันเดียวกัน


def monitor_at():
    """(ชั่วโมง, นาที) จาก MONITOR_AT หรือ None ถ้าไม่ได้ตั้ง/รูปแบบผิด"""
    raw = os.environ.get("MONITOR_AT", "").strip()
    try:
        hh, mm = (int(x) for x in raw.split(":"))
        return (hh, mm) if 0 <= hh < 24 and 0 <= mm < 60 else None
    except ValueError:
        return None


def daily_due(now, at, last):
    """ถึงเวลารันรายวันแล้ว และวันนี้ยังไม่ได้รัน (worker ปิดอยู่ตอนถึงเวลา = รันทันทีที่เปิดในวันเดียวกัน)"""
    return at is not None and (now.hour, now.minute) >= at and last != now.date().isoformat()


def main():
    db.init_db()
    stale = db.fail_running_jobs("worker ถูกรีสตาร์ทระหว่างรัน กรุณากดวิเคราะห์ใหม่")
    at = monitor_at()
    monitor.log(f"[{db.now()}] worker เริ่มทำงาน · รันรายวัน: "
                + (f"{at[0]:02d}:{at[1]:02d}" if at else "ไม่ได้ตั้ง MONITOR_AT")
                + (f" · ปิดงานที่ค้าง {stale} งาน" if stale else ""), "step")
    if at and not LAST_DAILY.exists() and (datetime.now().hour, datetime.now().minute) >= at:
        LAST_DAILY.write_text(date.today().isoformat())  # deploy ครั้งแรกหลังเลยเวลาแล้ว: เริ่มนับพรุ่งนี้ ไม่รันทันที
    while True:
        try:
            job_id = db.claim_job()
            if job_id:
                monitor.run_job(job_id)
                continue  # มีงานรออีกไหม หยิบต่อเลย
            last = LAST_DAILY.read_text().strip() if LAST_DAILY.exists() else ""
            if daily_due(datetime.now(), at, last):
                LAST_DAILY.write_text(date.today().isoformat())  # เขียนก่อนรัน: พังกลางทางไม่วนรันซ้ำทั้งวัน
                monitor.run_all()
        except Exception:  # worker ต้องไม่ตาย งานถัดไปยังต้องรันได้
            monitor.log(traceback.format_exc())
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
