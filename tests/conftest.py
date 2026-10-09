"""เทสฟังก์ชันที่ไม่ต้องใช้เน็ตหรือ LLM · ทุกเทสที่ใช้ DB ได้ฐานข้อมูลใหม่ในโฟลเดอร์ชั่วคราว
รัน: .venv\\Scripts\\python -m pytest"""
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import db  # noqa: E402


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DATA_DIR", tmp_path)
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "app.db")
    db.init_db()
    return db


def news(rows):
    """DataFrame แบบเดียวกับ analyze.load_df: company, title, url, summary, content, category, sentiment,
    source_type, published_dt (UTC), fetched_at"""
    df = pd.DataFrame(rows)
    for col, default in (("summary", ""), ("content", ""), ("category", "news_pr"), ("sentiment", "neutral"),
                         ("source_type", "news"), ("url", "https://example.com"), ("fetched_at", "2026-10-01T00:00:00")):
        if col not in df:
            df[col] = default
    df["published_dt"] = pd.to_datetime(df["published"], utc=True)
    return df
