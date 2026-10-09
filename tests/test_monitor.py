import pandas as pd

from core import monitor
from tests.conftest import news

PREV = "2026-10-01T00:00:00"


def test_new_financials_and_negative_news():
    df = news([
        {"company": "A", "title": "ข่าวลบใหม่", "sentiment": "negative", "published": "2026-10-05T03:00:00Z",
         "fetched_at": "2026-10-05T09:00:00"},
        {"company": "A", "title": "ข่าวเก่า", "sentiment": "negative", "published": "2026-09-20T03:00:00Z",
         "fetched_at": "2026-09-20T09:00:00"},
    ])
    snap = {"A": {"fin_period": "9M/2026", "net_profit_yoy_pct": 12.0}}
    prev = {"A": (PREV, {"fin_period": "6M/2026"})}
    kinds = {c["kind"]: c for c in monitor.changes(["A"], df, snap, prev)}
    assert kinds["financials"]["level"] == "high" and "+12.0%" in kinds["financials"]["text"]
    assert kinds["negative"]["items"][0]["title"] == "ข่าวลบใหม่"


def test_no_previous_run_no_alerts():
    df = news([{"company": "A", "title": "x", "published": "2026-10-05T03:00:00Z"}])
    assert monitor.changes(["A"], df, {"A": {}}, {}) == []


def test_new_price_move_alert_only_when_previous_tracked_it():
    df = news([{"company": "A", "title": "x", "published": "2026-09-01T03:00:00Z", "fetched_at": PREV}])
    events = pd.DataFrame([{"company": "A", "symbol": "AAA", "date": "2026-09-29", "r1_pct": 5.0, "r3_pct": 12.6,
                            "ar1_pct": 5.0, "ar3_pct": 14.9, "market_r3_pct": -2.4, "adjusted": True, "z": 3.2,
                            "titles": ["ข่าว"], "urls": ["https://n/1"]}])
    snap = {"A": {"price_moves": ["2026-09-29"]}}
    assert [c["kind"] for c in monitor.changes(["A"], df, snap, {"A": (PREV, {"price_moves": []})}, events)] \
        == ["price_move"]
    # รอบก่อนยังไม่มีข้อมูลราคา → ไม่เตือนย้อนหลัง
    assert monitor.changes(["A"], df, snap, {"A": (PREV, {})}, events) == []
