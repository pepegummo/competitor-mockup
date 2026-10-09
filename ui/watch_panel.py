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


def _save_form(res):
    top = [c for c in res["companies"] if c not in res.get("groups", {})]
    with st.form("watch_save", border=False):
        c1, c2 = st.columns([4, 1], vertical_alignment="bottom")
        name = c1.text_input("ชื่อชุด", value=" vs ".join(top)[:80])
        if c2.form_submit_button("บันทึกชุดนี้", icon=":material/bookmark_add:", width="stretch"):
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
            if c2.button("เปิดผลล่าสุด", key=f"w_open_{w['id']}", disabled=not last, width="stretch"):
                on_open(last["id"])
                opened = True
            if c3.button("รันตอนนี้", key=f"w_run_{w['id']}", width="stretch",
                         help="รันเบื้องหลัง ใช้เวลาหลายนาที เสร็จแล้วกด “เปิดผลล่าสุด”"):
                start_background("--id", str(w["id"]))
                st.toast(f"เริ่มรัน {w['name']} เบื้องหลังแล้ว")
            if c4.button("ลบ", key=f"w_del_{w['id']}", icon=":material/delete:", help="ลบชุดนี้"):
                db.delete_watchlist(w["id"])
                st.rerun()
    return opened


def _schedule():
    st.markdown("**ตั้งเวลารันทุกวัน**")
    if os.name != "nt":
        st.code(f"0 8 * * * {_python(False)} {SCRIPT}", language="bash")
        st.caption("ใส่บรรทัดนี้ใน crontab (crontab -e)")
        return
    exists, info = _schtasks("/Query", "/TN", TASK, "/FO", "LIST")
    c1, c2, c3 = st.columns([1.2, 1.6, 1.6], vertical_alignment="bottom")
    at = c1.time_input("เวลา", value=time(8, 0), step=1800)
    if c2.button("ตั้งเวลา" if not exists else "เปลี่ยนเวลา", icon=":material/schedule:", width="stretch"):
        ok, msg = _schtasks("/Create", "/F", "/SC", "DAILY", "/TN", TASK, "/ST", at.strftime("%H:%M"),
                            "/TR", f'"{_python()}" "{SCRIPT}"')
        st.toast("ตั้งเวลาแล้ว" if ok else f"ตั้งเวลาไม่สำเร็จ: {msg}")
        st.rerun()
    if c3.button("ยกเลิกการตั้งเวลา", icon=":material/alarm_off:", disabled=not exists, width="stretch"):
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
    st.markdown("**แจ้งเตือน**")
    if monitor.webhook_url():
        c1, c2 = st.columns([3, 1], vertical_alignment="center")
        c1.caption("ส่งแจ้งเตือนเมื่อมีเรื่องสำคัญ (แจ้งตลาดใหม่ งบใหม่ ข่าวลบใหม่ ข่าวลบ/ดาวรีวิวเปลี่ยนแรง) "
                   "ไปที่ webhook ใน .env")
        if c2.button("ทดสอบส่ง", icon=":material/send:", width="stretch"):
            ok, msg = monitor.send_alert("📊 Competitor Compare: ทดสอบการแจ้งเตือน")
            st.toast(msg)
    else:
        st.caption("ยังไม่ได้ตั้งช่องทางแจ้งเตือน ผลยังดูได้ในแอป ถ้าต้องการให้ส่งเข้าแชต ใส่ webhook ของ "
                   "Discord / Slack / Microsoft Teams / Google Chat ในไฟล์ `.env` แล้วรีสตาร์ทแอป:")
        st.code("ALERT_WEBHOOK_URL=https://discord.com/api/webhooks/...", language="bash")


def _log():
    if LOG.exists():
        with st.popover("บันทึกการรันอัตโนมัติ", icon=":material/receipt_long:"):
            lines = LOG.read_text(encoding="utf-8", errors="replace").splitlines()
            st.code("\n".join(lines[-60:]) or "-", language=None)


def render(res, on_open):
    """คืน True ถ้าผู้ใช้กดเปิดผลของรอบอื่น (หน้าต้อง rerun)"""
    count = len(db.watchlists())
    with st.expander(f"ติดตามอัตโนมัติ ({count} ชุด)" if count else "ติดตามอัตโนมัติ",
                     icon=":material/notifications_active:", expanded=True):
        st.caption("บันทึกชุดบริษัทที่วิเคราะห์ไว้ ระบบจะดึงข้อมูลใหม่ เทียบกับรอบก่อน "
                   "และบอกว่าอะไรเปลี่ยน (ทั้งในแอปและส่งแจ้งเตือน)")
        if res:
            _save_form(res)
        opened = _watch_list(on_open)
        st.divider()
        _schedule()
        _alerts()
        _log()
    return opened
