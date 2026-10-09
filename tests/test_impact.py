"""ราคาหุ้นหลังข่าว: ใช้ราคาสมมติที่รู้คำตอบ"""
import pandas as pd
import pytest

from core import impact
from tests.conftest import news

DAYS = pd.bdate_range("2026-08-03", periods=40)
EVENT = DAYS[30]


def prices(jump=0.10, wiggle=0.003):
    """ราคาแกว่งเล็กน้อยทุกวัน แล้วกระโดด jump ในวัน EVENT"""
    p, out = 100.0, []
    for i, d in enumerate(DAYS):
        p *= 1 + (wiggle if i % 2 else -wiggle)
        if d == EVENT:
            p *= 1 + jump
        out.append({"date": d.date().isoformat(), "close": round(p, 4)})
    return out


def setup(tmp_db, monkeypatch, stock, index):
    tmp_db.set_cache("px:AAA", stock)
    tmp_db.set_cache("px:^SET", index)
    monkeypatch.setattr(impact, "_market", lambda symbol: "SET")


def event_news(hour_utc=3):
    return news([{"company": "AAA Co", "title": "AAA ประกาศดีล", "sentiment": "positive",
                  "published": f"{EVENT.date()}T{hour_utc:02d}:00:00Z"}])


def test_stock_jump_flat_market_is_abnormal(tmp_db, monkeypatch):
    setup(tmp_db, monkeypatch, prices(0.10), prices(0.0, wiggle=0.002))
    ev = impact.events(event_news(), {"AAA Co": "AAA"})
    row = ev.iloc[0]
    assert row["date"] == EVENT.date().isoformat()
    assert row["r1_pct"] == pytest.approx(9.67, abs=0.05)  # 1.10 × 0.997 (วันนั้นแกว่งลง 0.3%)
    assert row["ar1_pct"] == pytest.approx(9.87, abs=0.05)  # หักตลาดที่ลง 0.2% วันเดียวกัน
    assert row["adjusted"] and row["big"]


def test_market_moved_too_is_not_abnormal(tmp_db, monkeypatch):
    setup(tmp_db, monkeypatch, prices(0.10), prices(0.10, wiggle=0.002))
    row = impact.events(event_news(), {"AAA Co": "AAA"}).iloc[0]
    assert abs(row["ar1_pct"]) < 1
    assert not row["big"]


def test_news_after_close_counts_next_day(tmp_db, monkeypatch):
    setup(tmp_db, monkeypatch, prices(0.10), prices(0.0, wiggle=0.002))
    # 10:00 UTC = 17:00 เวลาไทย หลังตลาดปิด → นับเป็นวันทำการถัดไป
    row = impact.events(event_news(hour_utc=10), {"AAA Co": "AAA"}).iloc[0]
    assert row["date"] == DAYS[31].date().isoformat()


def test_describe_mentions_market():
    row = {"r1_pct": 5.0, "r3_pct": -7.56, "ar1_pct": 4.0, "ar3_pct": -6.74, "market_r3_pct": -0.83,
           "adjusted": True, "z": -4.4}
    text = impact.describe(row)
    assert "-7.6%" in text and "ตลาด -0.8%" in text and "-6.7%" in text and "4.4 เท่า" in text
