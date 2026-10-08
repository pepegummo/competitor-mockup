import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "app.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS companies (
  id INTEGER PRIMARY KEY,
  name TEXT UNIQUE,
  role TEXT,            -- 'self' | 'competitor'
  website TEXT,
  origin TEXT           -- 'user' | 'discovered'
);

CREATE TABLE IF NOT EXISTS documents (
  id INTEGER PRIMARY KEY,
  company_id INTEGER REFERENCES companies(id),
  source_type TEXT,     -- 'news' | 'website'
  url TEXT,
  title TEXT,
  published_at TEXT,
  content_hash TEXT UNIQUE,
  raw_path TEXT,
  fetched_at TEXT
);

CREATE TABLE IF NOT EXISTS facts (
  id INTEGER PRIMARY KEY,
  document_id INTEGER REFERENCES documents(id),
  company_id INTEGER REFERENCES companies(id),
  category TEXT,
  sentiment TEXT,       -- 'positive' | 'neutral' | 'negative'
  summary TEXT,
  data_json TEXT
);

CREATE TABLE IF NOT EXISTS reports (
  id INTEGER PRIMARY KEY,
  mode TEXT,            -- 'phase1' | 'phase2' | 'phase3'
  created_at TEXT,
  content_md TEXT
);
"""


@contextmanager
def connect():
    """เปิด connection, commit เมื่อสำเร็จ แล้วปิดเสมอ"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def now():
    return datetime.now().isoformat(timespec="seconds")


# คอลัมน์ที่เพิ่มทีหลัง: DB เก่าจะถูกเพิ่มคอลัมน์ให้อัตโนมัติ
MIGRATIONS = {
    "companies": {"aliases": "TEXT", "play_app_id": "TEXT", "appstore_id": "TEXT"},
    "documents": {"source_name": "TEXT", "content": "TEXT", "rating": "INTEGER"},
}


def init_db():
    with connect() as conn:
        conn.executescript(SCHEMA)
        for table, cols in MIGRATIONS.items():
            have = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
            for col, typ in cols.items():
                if col not in have:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typ}")


def upsert_company(name, role="competitor", website=None, origin="user"):
    """คืน id ของบริษัท ถ้ามีอยู่แล้วจะอัปเดต role/website/origin"""
    with connect() as conn:
        conn.execute(
            """INSERT INTO companies (name, role, website, origin) VALUES (?, ?, ?, ?)
               ON CONFLICT(name) DO UPDATE SET
                 role = excluded.role,
                 website = COALESCE(excluded.website, companies.website),
                 origin = excluded.origin""",
            (name, role, website, origin),
        )
        return conn.execute("SELECT id FROM companies WHERE name = ?", (name,)).fetchone()["id"]


def insert_document(company_id, source_type, url, title, published_at, content_hash, raw_path,
                    source_name=None, content=None, rating=None):
    """คืน True ถ้าเพิ่มแถวใหม่, False ถ้า hash ซ้ำ (ข้าม)"""
    with connect() as conn:
        cur = conn.execute(
            """INSERT OR IGNORE INTO documents
               (company_id, source_type, url, title, published_at, content_hash, raw_path, fetched_at,
                source_name, content, rating)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (company_id, source_type, url, title, published_at, content_hash, raw_path, now(),
             source_name, content, rating),
        )
        return cur.rowcount == 1


def existing_hashes(hashes):
    if not hashes:
        return set()
    with connect() as conn:
        return {r[0] for r in conn.execute(
            f"SELECT content_hash FROM documents WHERE content_hash IN ({_in(hashes)})", hashes)}


def title_keys(company_id):
    """หัวข้อ (แบบ normalize) ของเอกสารที่ไม่ใช่รีวิวของบริษัทนี้ ใช้กันข่าวซ้ำข้ามแหล่ง"""
    from core.collect import title_key
    with connect() as conn:
        rows = conn.execute(
            "SELECT title FROM documents WHERE company_id = ? AND COALESCE(source_type, 'news') != 'review'",
            (company_id,)).fetchall()
    return {title_key(r["title"]) for r in rows}


def get_companies(names):
    """แถวบริษัทพร้อมการตั้งค่าแหล่งข้อมูล เรียงตาม names (ข้ามชื่อที่ไม่มีใน DB)"""
    if not names:
        return []
    with connect() as conn:
        rows = {r["name"]: dict(r) for r in conn.execute(
            f"SELECT * FROM companies WHERE name IN ({_in(names)})", names)}
    out = []
    for n in names:
        if n in rows:
            r = rows[n]
            r["aliases"] = json.loads(r["aliases"]) if r["aliases"] else []
            out.append(r)
    return out


def update_company_sources(name, aliases=None, play_app_id=None, appstore_id=None, website=None):
    """บันทึกการตั้งค่าแหล่งข้อมูลของบริษัท (สร้างบริษัทถ้ายังไม่มี)"""
    with connect() as conn:
        conn.execute("INSERT OR IGNORE INTO companies (name, role, origin) VALUES (?, 'competitor', 'user')",
                     (name,))
        conn.execute(
            """UPDATE companies SET aliases = ?, play_app_id = ?, appstore_id = ?, website = ?
               WHERE name = ?""",
            (json.dumps(aliases or [], ensure_ascii=False), play_app_id or None,
             appstore_id or None, website or None, name),
        )


def insert_fact(document_id, company_id, category, sentiment, summary, data_json=None):
    with connect() as conn:
        conn.execute(
            """INSERT INTO facts (document_id, company_id, category, sentiment, summary, data_json)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (document_id, company_id, category, sentiment, summary, data_json),
        )


def _in(ids):
    return ",".join("?" * len(ids))


def unprocessed_documents(company_ids):
    """documents ที่ยังไม่มีใน facts"""
    if not company_ids:
        return []
    with connect() as conn:
        return conn.execute(
            f"""SELECT d.id, d.company_id, d.title, d.content, d.source_type, d.source_name,
                       c.name AS company
                FROM documents d JOIN companies c ON c.id = d.company_id
                WHERE d.company_id IN ({_in(company_ids)})
                  AND d.id NOT IN (SELECT document_id FROM facts)
                ORDER BY d.company_id, d.id""",
            company_ids,
        ).fetchall()


def facts_df(company_ids):
    """facts รวมข้อมูลข่าวและบริษัท เป็น DataFrame"""
    if not company_ids:
        return pd.DataFrame()
    with connect() as conn:
        return pd.read_sql_query(
            f"""SELECT c.name AS company, f.category, f.sentiment, f.summary,
                       d.title, d.url, d.published_at,
                       COALESCE(d.source_type, 'news') AS source_type,
                       COALESCE(d.source_name, '') AS source_name, d.rating, d.content
                FROM facts f
                JOIN documents d ON d.id = f.document_id
                JOIN companies c ON c.id = f.company_id
                WHERE f.company_id IN ({_in(company_ids)})""",
            conn,
            params=company_ids,
        )


def count_rows(table):
    with connect() as conn:
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def company_names():
    with connect() as conn:
        return [r["name"] for r in conn.execute("SELECT name FROM companies ORDER BY name")]


def last_fetched_at(company_ids):
    if not company_ids:
        return None
    with connect() as conn:
        return conn.execute(
            f"SELECT MAX(fetched_at) FROM documents WHERE company_id IN ({_in(company_ids)})",
            company_ids,
        ).fetchone()[0]


def company_ids(names):
    """หา id จากชื่อ (ไม่สร้างใหม่) เรียงตาม names, ข้ามชื่อที่ไม่มีใน DB"""
    if not names:
        return []
    with connect() as conn:
        rows = conn.execute(
            f"SELECT name, id FROM companies WHERE name IN ({_in(names)})", names
        ).fetchall()
    found = {r["name"]: r["id"] for r in rows}
    return [found[n] for n in names if n in found]


def get_report(report_id):
    with connect() as conn:
        return conn.execute(
            "SELECT id, created_at, content_md FROM reports WHERE id = ?", (report_id,)
        ).fetchone()


def latest_report(mode):
    """คืน row (id, created_at, content_md) ของรายงานล่าสุด หรือ None"""
    with connect() as conn:
        return conn.execute(
            "SELECT id, created_at, content_md FROM reports WHERE mode = ? ORDER BY id DESC LIMIT 1",
            (mode,),
        ).fetchone()


def save_report(mode, content_md):
    with connect() as conn:
        conn.execute(
            "INSERT INTO reports (mode, created_at, content_md) VALUES (?, ?, ?)",
            (mode, now(), content_md),
        )
