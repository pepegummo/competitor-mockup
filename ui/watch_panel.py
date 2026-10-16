"""ติดตามอัตโนมัติ: บันทึกชุดบริษัทที่วิเคราะห์ไว้ ตั้งเวลาให้ Windows รันทุกวัน และตั้งค่าแจ้งเตือน"""
import os
import subprocess
import sys
from datetime import time
from pathlib import Path

import streamlit as st

from core import db, monitor
from ui.common import fmt_time

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "monitor.py"
LOG = db.DATA_DIR / "monitor.log"
TASK = "CompetitorCompareMonitor"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
# docker: ไม่รัน monitor.py เอง แค่ใส่งานลงตาราง jobs ให้ container worker (worker.py) หยิบ และรันรายวันตาม MONITOR_AT
QUEUE = os.environ.get("CC_JOB_QUEUE", "").strip().lower() in ("1", "true", "yes")


def _python(background=True):
    """pythonw ไม่เปิดหน้าต่าง console ตอนรันเบื้องหลัง"""
    exe = Path(sys.executable)
    quiet = exe.with_name("pythonw.exe")
    return quiet if background and quiet.exists() else exe


def _schtasks(*args):
    try:
        r = subprocess.run(["schtasks", *args], capture_output=True, text=True, errors="replace",
                           creationflags=NO_WINDOW, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, str(e)
    return r.returncode == 0, (r.stdout or r.stderr).strip()


def start_background(*args):
    """รัน monitor.py เบื้องหลัง (ไม่มีหน้าต่าง) ส่ง environment เดิมไปด้วย เช่น CC_DATA_DIR, LLM_REPLAY"""
    subprocess.Popen([str(_python()), str(SCRIPT), *args], cwd=ROOT, creationflags=NO_WINDOW,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def submit_job(config):
    """สร้างงานวิเคราะห์ในตาราง jobs คืน id · docker: รอ worker หยิบ · บนเครื่อง: รัน monitor.py --job ทันที"""
    if QUEUE:
        return db.create_job(config, status="queued")
    job_id = db.create_job(config)
    start_background("--job", str(job_id))
    return job_id


def run_watch_now(watch_id):
    if QUEUE:
        db.create_job({"watch_id": watch_id}, status="queued")
    else:
        start_background("--id", str(watch_id))


def save_form(res):
    top = [c for c in res["companies"] if c not in res.get("groups", {})]
    with st.form("watch_save", border=False):
        c1, c2 = st.columns([4, 1], vertical_alignment="bottom")
        name = c1.text_input("ชื่อชุด", value=" vs ".join(top)[:80])
        if c2.form_submit_button("Save this watchlist", icon=":material/bookmark_add:", width="stretch"):
            config = dict(companies=res["companies"], self_name=res["self_name"], mode=res["mode"],
                          focus=res["focus"], groups=res.get("groups", {}), opts=res.get("opts"))
            db.save_watchlist(name.strip() or " vs ".join(top), config)
            st.toast("บันทึกชุดติดตามแล้ว")
    if not res.get("opts"):
        st.caption("ผลนี้มาจากเวอร์ชันก่อน ระบบจะใช้แหล่งข้อมูลพื้นฐาน (Google News) ถ้าต้องการทุกแหล่ง "
                   "ให้กดวิเคราะห์ใหม่ 1 ครั้งก่อนบันทึก")


def _watch_list(on_open):
    opened = False
    for w in db.watchlists():
        last = w["last_run"]
        high = sum(c["level"] == "high" for c in last["changes"]) if last else 0
        with st.container(border=True):
            c1, c2, c3, c4 = st.columns([5, 1.4, 1.2, 0.8], vertical_alignment="center")
            c1.markdown(f"**{w['name']}**" + (f"  :red-badge[สำคัญ {high} เรื่อง]" if high else ""))
            c1.caption(", ".join(w["config"]["companies"]) + " · "
                       + (f"รันล่าสุด {fmt_time(last['started_at'])}" if last else "ยังไม่เคยรัน"))
            if c2.button("Open latest result", key=f"w_open_{w['id']}", disabled=not last, width="stretch"):
                on_open(last["id"])
                opened = True
            if c3.button("Run now", key=f"w_run_{w['id']}", width="stretch",
                         help="รันเบื้องหลัง ใช้เวลาหลายนาที เสร็จแล้วกด “เปิดผลล่าสุด”"):
                run_watch_now(w["id"])
                st.toast(f"เริ่มรัน {w['name']} เบื้องหลังแล้ว")
            if c4.button("", key=f"w_del_{w['id']}", icon=":material/delete:", help="Delete this watchlist"):
                db.delete_watchlist(w["id"])
                st.rerun()
    return opened


def _admin():
    """ส่วนสำหรับผู้ดูแลระบบ (คำสั่ง/ไฟล์ตั้งค่า) พับไว้ ผู้ใช้ทั่วไปไม่ต้องเปิด"""
    return st.expander("For administrators", icon=":material/admin_panel_settings:")


def _schedule():
    st.markdown("**Daily schedule**")
    if QUEUE:
        at = os.environ.get("MONITOR_AT", "").strip()
        st.caption(f"ระบบรันทุกชุดในรายการอัตโนมัติทุกวันเวลา {at} น." if at
                   else "ยังไม่ได้ตั้งเวลารันอัตโนมัติ ติดต่อผู้ดูแลระบบเพื่อตั้งเวลา")
        with _admin():
            st.caption("ตั้งด้วย MONITOR_AT ในไฟล์ .env บนเซิร์ฟเวอร์ แล้วรัน `docker compose up -d`")
            st.code("MONITOR_AT=07:00", language="bash")
        return
    if os.name != "nt":
        st.caption("ยังไม่ได้ตั้งเวลารันอัตโนมัติบนเครื่องนี้ ติดต่อผู้ดูแลระบบเพื่อตั้งเวลา "
                   "(ระหว่างนี้กด Run now ในแต่ละชุดด้านบนได้)")
        with _admin():
            st.caption("ใส่บรรทัดนี้ใน crontab (crontab -e)")
            st.code(f"0 8 * * * {_python(False)} {SCRIPT}", language="bash")
        return
    exists, info = _schtasks("/Query", "/TN", TASK, "/FO", "LIST")
    c1, c2, c3 = st.columns([1.2, 1.6, 1.6], vertical_alignment="bottom")
    at = c1.time_input("เวลา", value=time(8, 0), step=1800)
    if c2.button("Set schedule" if not exists else "Change schedule", icon=":material/schedule:", width="stretch"):
        ok, msg = _schtasks("/Create", "/F", "/SC", "DAILY", "/TN", TASK, "/ST", at.strftime("%H:%M"),
                            "/TR", f'"{_python()}" "{SCRIPT}"')
        st.toast("ตั้งเวลาแล้ว" if ok else f"ตั้งเวลาไม่สำเร็จ: {msg}")
        st.rerun()
    if c3.button("Remove schedule", icon=":material/alarm_off:", disabled=not exists, width="stretch"):
        ok, msg = _schtasks("/Delete", "/F", "/TN", TASK)
        st.toast("ยกเลิกแล้ว" if ok else f"ยกเลิกไม่สำเร็จ: {msg}")
        st.rerun()
    if exists:
        st.caption(f"ตั้งไว้แล้วใน Windows Task Scheduler ชื่อ {TASK} · รันทุกชุดในรายการ "
                   "(ต้องเปิดเครื่องและล็อกอินอยู่ ถ้าเครื่องปิด/หลับ รอบนั้นจะถูกข้าม)")
    else:
        st.caption("ยังไม่ได้ตั้งเวลา · ระบบจะรันทุกชุดในรายการวันละครั้งผ่าน Windows Task Scheduler "
                   "(ใช้ LLM ประมาณ 1 ครั้งต่อข่าวใหม่ 10 ข่าว + 1 ครั้งต่อชุด)")


def _alerts():
    st.markdown("**Alerts**")
    if monitor.webhook_url():
        c1, c2 = st.columns([3, 1], vertical_alignment="center")
        c1.caption("ส่งแจ้งเตือนเมื่อมีเรื่องสำคัญ (แจ้งตลาดใหม่ งบใหม่ ข่าวลบใหม่ ข่าวลบ/ดาวรีวิวเปลี่ยนแรง) "
                   "ไปยังช่องทางแชตที่ผู้ดูแลระบบตั้งไว้")
        if c2.button("Send test", icon=":material/send:", width="stretch"):
            ok, msg = monitor.send_alert("📊 Competitor Compare: ทดสอบการแจ้งเตือน")
            st.toast(msg)
    else:
        st.caption("ยังไม่ได้ตั้งช่องทางแจ้งเตือน ผลยังดูได้ในแอป ถ้าต้องการให้ส่งเข้าแชต "
                   "(Discord / Slack / Microsoft Teams / Google Chat) ติดต่อผู้ดูแลระบบ")
        with _admin():
            st.caption("ใส่ webhook ในไฟล์ `.env` แล้วรีสตาร์ทแอป:")
            st.code("ALERT_WEBHOOK_URL=https://discord.com/api/webhooks/...", language="bash")


def _log():
    if LOG.exists():
        with _admin():
            lines = LOG.read_text(encoding="utf-8", errors="replace").splitlines()
            st.caption("Auto-run log (60 บรรทัดล่าสุด)")
            st.code("\n".join(lines[-60:]) or "-", language=None)


def render(res, on_open):
    """คืน True ถ้าผู้ใช้กดเปิดผลของรอบอื่น (หน้าต้องเปลี่ยนไปภาพรวม)"""
    st.caption("บันทึกชุดบริษัทที่วิเคราะห์ไว้ ระบบจะดึงข้อมูลใหม่ เทียบกับรอบก่อน "
               "และบอกว่าอะไรเปลี่ยน (ทั้งในแอปและส่งแจ้งเตือน)")
    if res:
        with st.container(border=True):
            st.markdown("**บันทึกผลที่เปิดอยู่เป็นชุดติดตาม**")
            save_form(res)
    count = len(db.watchlists())
    st.subheader(f"Watchlists ({count})" if count else "Watchlists", divider="gray")
    if not count:
        st.caption("ยังไม่มีชุดติดตาม วิเคราะห์ก่อน แล้วกด “ติดตามชุดนี้” ในหน้าภาพรวม หรือบันทึกด้านบน")
    opened = _watch_list(on_open)
    st.subheader("Schedule & Alerts", divider="gray")
    _schedule()
    _alerts()
    _log()
    return opened
