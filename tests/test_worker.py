"""คิวงานในตาราง jobs และเวลารันรายวันของ worker.py (container worker ใน docker)"""
from datetime import datetime

import worker


def test_claim_job_takes_oldest_queued_once(tmp_db):
    running = tmp_db.create_job({"companies": ["A"]})  # งานแบบรันบนเครื่อง ไม่ใช่คิว
    first = tmp_db.create_job({"companies": ["B"]}, status="queued")
    second = tmp_db.create_job({"companies": ["C"]}, status="queued")
    assert tmp_db.claim_job() == first
    assert tmp_db.claim_job() == second
    assert tmp_db.claim_job() is None
    assert tmp_db.get_job(first)["status"] == "running"
    assert tmp_db.get_job(running)["status"] == "running"


def test_fail_running_jobs_leaves_queued(tmp_db):
    stuck = tmp_db.create_job({}, status="running")
    waiting = tmp_db.create_job({}, status="queued")
    assert tmp_db.fail_running_jobs("รีสตาร์ท") == 1
    job = tmp_db.get_job(stuck)
    assert (job["status"], job["error"]) == ("error", "รีสตาร์ท")
    assert tmp_db.get_job(waiting)["status"] == "queued"


def test_monitor_at(monkeypatch):
    for raw, want in (("07:00", (7, 0)), ("7:30", (7, 30)), ("", None), ("25:00", None), ("เจ็ดโมง", None)):
        monkeypatch.setenv("MONITOR_AT", raw)
        assert worker.monitor_at() == want


def test_daily_due():
    at = (7, 0)
    assert not worker.daily_due(datetime(2026, 10, 12, 6, 59), at, "2026-10-11")
    assert worker.daily_due(datetime(2026, 10, 12, 7, 0), at, "2026-10-11")
    assert worker.daily_due(datetime(2026, 10, 12, 15, 0), at, "")  # worker ปิดตอน 7 โมง: เปิดแล้วรันวันนั้นเลย
    assert not worker.daily_due(datetime(2026, 10, 12, 15, 0), at, "2026-10-12")
    assert not worker.daily_due(datetime(2026, 10, 12, 15, 0), None, "")


def test_queue_mode_submits_without_spawning(tmp_db, monkeypatch):
    from ui import watch_panel
    monkeypatch.setattr(watch_panel, "QUEUE", True)
    monkeypatch.setattr(watch_panel, "start_background", lambda *a: (_ for _ in ()).throw(AssertionError(a)))
    job_id = watch_panel.submit_job({"companies": ["A"]})
    watch_panel.run_watch_now(3)
    assert tmp_db.get_job(job_id)["status"] == "queued"
    assert tmp_db.get_job(tmp_db.claim_job())["config"] == {"companies": ["A"]}
    assert tmp_db.get_job(tmp_db.claim_job())["config"] == {"watch_id": 3}
