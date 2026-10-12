"""ฐานข้อมูลของทั้งแอป: ทุกคำสั่ง SQL อยู่ในไฟล์นี้ ไฟล์อื่นเรียกผ่านฟังก์ชันเท่านั้น
ตั้ง DATABASE_URL (postgresql://...) = ใช้ PostgreSQL (RDS หรือ container db) · ไม่ตั้ง = SQLite ไฟล์ data/app.db (เดโม/เทส)
SQL เขียนแบบเดียวใช้ได้ทั้งสองแบบ (ใช้ ? เป็นตัวแทนค่า) ยกเว้นจุดที่แยกด้วย _pg()"""
import atexit
import json
import logging
import os
import random
import re
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd
from dotenv import load_dotenv

load_dotenv()
ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("CC_DATA_DIR") or ROOT / "data")  # ตั้ง CC_DATA_DIR เพื่อทดสอบกับข้อมูลชุดอื่น
DB_PATH = DATA_DIR / "app.db"
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()

log = logging.getLogger(__name__)

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
  source_type TEXT,     -- 'news' | 'rss' | 'website' | 'set' | 'review' | 'document' (PDF ที่อัปโหลด)
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

CREATE TABLE IF NOT EXISTS financials (
  company_id INTEGER PRIMARY KEY REFERENCES companies(id),
  symbol TEXT,
  fetched_at TEXT,
  data_json TEXT        -- ผลจาก set_api.financials() (เก็บไว้แสดงผลซ้ำได้โดยไม่ต้องดึงใหม่)
);

CREATE TABLE IF NOT EXISTS company_groups (
  name TEXT PRIMARY KEY, -- ชื่อบริษัท/เครือตามที่ผู้ใช้กรอก
  fetched_at TEXT,
  data_json TEXT        -- ผลจาก group.find_groups() (บริษัทในเครือพร้อมหลักฐาน) ไม่ต้องถาม LLM ซ้ำ
);

CREATE TABLE IF NOT EXISTS watchlists (
  id INTEGER PRIMARY KEY,
  name TEXT,
  created_at TEXT,
  config_json TEXT      -- ชุดที่ต้องติดตาม: companies, self_name, mode, focus, groups, opts
);

CREATE TABLE IF NOT EXISTS runs (
  id INTEGER PRIMARY KEY,
  watch_id INTEGER,     -- NULL = ผู้ใช้กดวิเคราะห์เองในแอป
  started_at TEXT,      -- เวลาที่รอบนี้วิเคราะห์เสร็จ
  config_json TEXT,
  snapshot_json TEXT,   -- ตัวเลขต่อบริษัท ณ รอบนี้ (ใช้เทียบกับรอบถัดไป)
  changes_json TEXT,    -- สิ่งที่เปลี่ยนไปจากรอบก่อน (monitor.changes)
  report_id INTEGER
);

CREATE TABLE IF NOT EXISTS internal_metrics (
  company TEXT,
  metric TEXT,
  value REAL,
  unit TEXT,
  period TEXT,
  uploaded_at TEXT,
  PRIMARY KEY (company, metric)  -- อัปโหลดซ้ำ = แทนค่าเดิม
);

CREATE TABLE IF NOT EXISTS llm_log (
  id INTEGER PRIMARY KEY,
  hash TEXT,             -- sha256 ของ model + system + prompt (ใช้เล่นคำตอบซ้ำเมื่อ LLM_REPLAY=1 หรือ LLM ล่ม)
  model TEXT,
  prompt TEXT,
  response TEXT,
  ms INTEGER,
  created_at TEXT
);
CREATE INDEX IF NOT EXISTS llm_log_hash ON llm_log(hash);

CREATE TABLE IF NOT EXISTS jobs (
  id INTEGER PRIMARY KEY,
  status TEXT,           -- 'queued' (รอ worker.py ใน docker) | 'running' | 'done' | 'error'
  config_json TEXT,      -- companies, self_name, mode, opts, focus, groups
  log TEXT,              -- บรรทัดความคืบหน้า (แสดงในแอประหว่างรัน)
  run_id INTEGER,
  error TEXT,
  started_at TEXT,
  finished_at TEXT
);

CREATE TABLE IF NOT EXISTS labels (
  fact_id INTEGER PRIMARY KEY REFERENCES facts(id),  -- ผู้ใช้ตรวจผลของระบบ (ใช้วัดความแม่น + ตัวอย่างให้ LLM)
  relevant INTEGER,      -- 1 = ข่าวนี้เป็นเรื่องของบริษัทนี้จริง
  category TEXT,         -- หมวดที่ถูก (NULL ถ้าไม่เกี่ยว)
  sentiment TEXT,
  labeled_at TEXT
);

CREATE TABLE IF NOT EXISTS market_cache (
  key TEXT PRIMARY KEY,  -- "hl:MC" ตัวเลขสรุปของหุ้น (เทียบทั้งหมวด), "px:MC" ราคาปิดรายวัน
  fetched_at TEXT,
  data_json TEXT
);

CREATE TABLE IF NOT EXISTS embeddings (
  hash TEXT PRIMARY KEY, -- sha256 ของ model + ชนิด (query/passage) + ข้อความ: ข้อความเดิมไม่ต้องคำนวณซ้ำ
  model TEXT,
  vec BLOB,              -- float32 ที่ normalize แล้ว (cosine = dot)
  created_at TEXT
);
"""


def _pg():
    return bool(DATABASE_URL)


class Row(dict):
    """แถวจาก PostgreSQL ที่อ่านได้ทั้ง r["name"] และ r[0] เหมือน sqlite3.Row"""

    def __getitem__(self, key):
        return list(self.values())[key] if isinstance(key, int) else super().__getitem__(key)


def _row_factory(cursor):
    names = [c.name for c in cursor.description or []]
    return lambda values: Row(zip(names, values))


@lru_cache(maxsize=512)
def _pg_sql(sql):
    return sql.replace("%", "%%").replace("?", "%s")


def _clean(value):
    if isinstance(value, np.generic):  # ตัวเลขจาก pandas/numpy
        return value.item()
    # PostgreSQL เก็บตัวอักษร NUL ใน text ไม่ได้ (ข่าวบางเว็บมี)
    return value.replace("\x00", "") if isinstance(value, str) else value


class _PgConn:
    """connection ของ psycopg ที่ใช้เหมือน sqlite3: execute / executemany รับตัวแทนค่า ?"""

    def __init__(self, conn):
        self.raw = conn

    def execute(self, sql, params=()):
        return self.raw.execute(_pg_sql(sql), [_clean(p) for p in params])

    def executemany(self, sql, rows):
        cur = self.raw.cursor()
        cur.executemany(_pg_sql(sql), [[_clean(p) for p in r] for r in rows])
        return cur


_pools = {}
_pool_lock = threading.Lock()


def _pool():
    """connection pool ต่อ process (เปิด connection ใหม่ทุกคำสั่งช้าเกินไปสำหรับ PostgreSQL)"""
    with _pool_lock:
        if DATABASE_URL not in _pools:
            from psycopg_pool import ConnectionPool  # ลงไว้เสมอ แต่ import เฉพาะตอนใช้ PostgreSQL
            _pools[DATABASE_URL] = ConnectionPool(DATABASE_URL, min_size=1, max_size=10, open=True,
                                                  kwargs={"row_factory": _row_factory})
        return _pools[DATABASE_URL]


@atexit.register
def _close_pools():
    for pool in _pools.values():
        pool.close()


@contextmanager
def connect():
    """เปิด connection, commit เมื่อสำเร็จ (rollback เมื่อ error) แล้วปิด/คืน pool เสมอ"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)  # log และข้อมูลดิบอยู่ในโฟลเดอร์นี้ แม้ DB จะเป็น PostgreSQL
    if _pg():
        with _pool().connection() as conn:
            yield _PgConn(conn)
        return
    conn = sqlite3.connect(DB_PATH, timeout=30)  # ดึง/จัดหมวดหลายเธรดพร้อมกัน: รอ lock แทนการ error
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def _df(conn, sql, params=()):
    """ผล SELECT เป็น DataFrame ใช้ได้ทั้งสองแบบ (pd.read_sql_query รับ connection ที่ห่อไว้ไม่ได้)"""
    cur = conn.execute(sql, params)
    cols = [c[0] for c in cur.description]
    rows = [list(r.values()) if isinstance(r, dict) else list(r) for r in cur.fetchall()]
    return pd.DataFrame.from_records(rows, columns=cols, coerce_float=True)


def now():
    return datetime.now().isoformat(timespec="seconds")


# คอลัมน์ที่เพิ่มทีหลัง: DB เก่าจะถูกเพิ่มคอลัมน์ให้อัตโนมัติ
MIGRATIONS = {
    "companies": {"aliases": "TEXT", "play_app_id": "TEXT", "appstore_id": "TEXT", "set_symbol": "TEXT",
                  "appstore_name": "TEXT", "play_name": "TEXT", "disabled_sources": "TEXT",
                  "business": "TEXT"},  # ธุรกิจหลัก (ให้ LLM แยกข่าวของบริษัทนี้ออกจากข่าวที่ชื่อซ้ำ)
    "documents": {"source_name": "TEXT", "content": "TEXT", "rating": "INTEGER"},
}


def _pg_schema(vector):
    """SCHEMA แบบ PostgreSQL: id เลขรันอัตโนมัติ · REAL ของ PostgreSQL ละเอียดแค่ 6 หลัก · เวกเตอร์เป็น vector หรือ bytea"""
    schema = re.sub(r"(?m)^(\s*)id INTEGER PRIMARY KEY", r"\1id SERIAL PRIMARY KEY", SCHEMA)
    return schema.replace(" REAL", " DOUBLE PRECISION").replace("vec BLOB", "vec vector" if vector else "vec BYTEA")


def _create_vector(conn):
    import psycopg
    try:
        with conn.raw.transaction():  # savepoint: สร้างไม่ได้ก็ทำต่อได้ใน transaction เดิม
            conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        return True
    except psycopg.Error as e:
        log.warning("เปิด pgvector ไม่ได้ (%s) เก็บเวกเตอร์เป็น bytes และคิดความใกล้ด้วย numpy แทน", e)
        return False


def init_db():
    with connect() as conn:
        if _pg():
            conn.execute("SELECT pg_advisory_xact_lock(7203)")  # web กับ worker เริ่มพร้อมกัน: สร้างตารางทีละตัว
            conn.raw.execute(_pg_schema(_create_vector(conn)))  # หลายคำสั่งในครั้งเดียว ส่งได้เมื่อไม่มีตัวแทนค่า
            for table, cols in MIGRATIONS.items():
                for col, typ in cols.items():
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {col} {typ}")
            return
        conn.executescript(SCHEMA)
        for table, cols in MIGRATIONS.items():
            have = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
            for col, typ in cols.items():
                if col not in have:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typ}")


def has_vector():
    """ค้นด้วยความหมายใน DB ได้ไหม: PostgreSQL ที่คอลัมน์ embeddings.vec เป็นชนิด vector (pgvector)"""
    if not _pg():
        return False
    if DATABASE_URL not in _vector_cols:
        with connect() as conn:
            row = conn.execute("SELECT udt_name FROM information_schema.columns WHERE table_schema = current_schema() "
                               "AND table_name = 'embeddings' AND column_name = 'vec'").fetchone()
        if not row:
            return False  # ยังไม่ได้ init_db: ไม่จำค่า
        _vector_cols[DATABASE_URL] = row["udt_name"] == "vector"
    return _vector_cols[DATABASE_URL]


_vector_cols = {}


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
            """INSERT INTO documents
               (company_id, source_type, url, title, published_at, content_hash, raw_path, fetched_at,
                source_name, content, rating)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT DO NOTHING""",
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
            r["disabled_sources"] = json.loads(r["disabled_sources"]) if r["disabled_sources"] else []
            out.append(r)
    return out


def update_company_sources(name, aliases=None, play_app_id=None, appstore_id=None, website=None,
                           set_symbol=None, appstore_name=None, play_name=None):
    """บันทึกการตั้งค่าแหล่งข้อมูลของบริษัท (สร้างบริษัทถ้ายังไม่มี)"""
    with connect() as conn:
        conn.execute("INSERT INTO companies (name, role, origin) VALUES (?, 'competitor', 'user') ON CONFLICT DO NOTHING",
                     (name,))
        conn.execute(
            # set_symbol: NULL = ยังไม่เคยหา (ระบบจะหาให้ตอนวิเคราะห์), '' = ไม่อยู่ในตลาด/ผู้ใช้ลบออก
            """UPDATE companies SET aliases = ?, play_app_id = ?, appstore_id = ?, website = ?,
                 set_symbol = CASE WHEN ? != '' THEN ? WHEN set_symbol IS NULL THEN NULL ELSE '' END,
                 appstore_name = ?, play_name = ?
               WHERE name = ?""",
            (json.dumps(aliases or [], ensure_ascii=False), play_app_id or None,
             appstore_id or None, website or None, *[(set_symbol or "").strip().upper()] * 2,
             appstore_name or None, play_name or None, name),
        )


def set_disabled_sources(name, keys):
    """แหล่งที่ปิดไว้เฉพาะบริษัทนี้ (key จาก collect.SOURCES และ "financials")"""
    with connect() as conn:
        conn.execute("INSERT INTO companies (name, role, origin) VALUES (?, 'competitor', 'user') ON CONFLICT DO NOTHING",
                     (name,))
        conn.execute("UPDATE companies SET disabled_sources = ? WHERE name = ?",
                     (json.dumps(sorted(set(keys))), name))


def set_company_profile(name, set_symbol, aliases=None):
    """บันทึกชื่อหุ้นที่ระบบหาให้ ('' = ไม่อยู่ในตลาด) และชื่อเรียกถ้ายังไม่มี"""
    with connect() as conn:
        conn.execute(
            """UPDATE companies SET set_symbol = ?,
                 aliases = CASE WHEN aliases IS NULL OR aliases = '[]' THEN ? ELSE aliases END
               WHERE name = ?""",
            (set_symbol.strip().upper(), json.dumps(aliases or [], ensure_ascii=False), name),
        )


def set_company_business(name, business):
    with connect() as conn:
        conn.execute("UPDATE companies SET business = ? WHERE name = ?", (business, name))


def save_financials(company_id, symbol, data):
    with connect() as conn:
        conn.execute(
            """INSERT INTO financials (company_id, symbol, fetched_at, data_json) VALUES (?, ?, ?, ?)
               ON CONFLICT(company_id) DO UPDATE SET
                 symbol = excluded.symbol, fetched_at = excluded.fetched_at, data_json = excluded.data_json""",
            (company_id, symbol, now(), json.dumps(data, ensure_ascii=False)),
        )


def financials_by_company(company_ids):
    """{ชื่อบริษัท: ข้อมูลงบ} ของบริษัทที่เคยดึงงบไว้ (บริษัทที่ไม่มีชื่อหุ้นตอนนี้จะไม่ถูกคืน)"""
    if not company_ids:
        return {}
    with connect() as conn:
        rows = conn.execute(
            f"""SELECT c.name, f.fetched_at, f.data_json FROM financials f
                JOIN companies c ON c.id = f.company_id
                WHERE f.company_id IN ({_in(company_ids)}) AND f.symbol = c.set_symbol""",
            company_ids).fetchall()
    return {r["name"]: {**json.loads(r["data_json"]), "fetched_at": r["fetched_at"]} for r in rows}


def save_group(name, data):
    with connect() as conn:
        conn.execute(
            """INSERT INTO company_groups (name, fetched_at, data_json) VALUES (?, ?, ?)
               ON CONFLICT(name) DO UPDATE SET fetched_at = excluded.fetched_at, data_json = excluded.data_json""",
            (name, now(), json.dumps(data, ensure_ascii=False)),
        )


def get_groups(names):
    """{ชื่อ: ผลการหาบริษัทในเครือ} เฉพาะชื่อที่เคยหาแล้ว"""
    if not names:
        return {}
    with connect() as conn:
        rows = conn.execute(f"SELECT name, data_json FROM company_groups WHERE name IN ({_in(names)})",
                            names).fetchall()
    return {r["name"]: json.loads(r["data_json"]) for r in rows}


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
        return _df(
            conn,
            f"""SELECT c.name AS company, f.category, f.sentiment, f.summary,
                       d.title, d.url, d.published_at,
                       COALESCE(d.source_type, 'news') AS source_type,
                       COALESCE(d.source_name, '') AS source_name, d.rating, d.content, d.fetched_at
                FROM facts f
                JOIN documents d ON d.id = f.document_id
                JOIN companies c ON c.id = f.company_id
                WHERE f.company_id IN ({_in(company_ids)})
                  AND f.category != 'irrelevant'  -- ข่าวที่ชื่อตรงแต่ไม่ใช่เรื่องของบริษัทนี้""",
            company_ids,
        )


def count_rows(table):
    with connect() as conn:
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def company_names():
    with connect() as conn:
        return [r["name"] for r in conn.execute("SELECT name FROM companies ORDER BY name")]


def analyzed_companies():
    """[{name, set_symbol}] บริษัทที่เคยดึงข้อมูลได้จริง (ไม่รวมแถวว่าง) ใช้เป็นประวัติในช่องเลือกบริษัท
    ถ้าหลายชื่อเป็นหุ้นตัวเดียวกัน (True / True Corporation / ทรู) เก็บชื่อที่มีข้อมูลมากสุด"""
    with connect() as conn:
        rows = conn.execute(
            """SELECT c.name, c.set_symbol, COUNT(d.id) AS n FROM companies c
               JOIN documents d ON d.company_id = c.id GROUP BY c.id ORDER BY n DESC""").fetchall()
    out, symbols = [], set()
    for r in rows:
        if r["set_symbol"]:
            if r["set_symbol"] in symbols:
                continue
            symbols.add(r["set_symbol"])
        out.append({"name": r["name"], "set_symbol": r["set_symbol"] or ""})
    return sorted(out, key=lambda r: r["name"].lower())


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
        return conn.execute(
            "INSERT INTO reports (mode, created_at, content_md) VALUES (?, ?, ?) RETURNING id",
            (mode, now(), content_md),
        ).fetchone()["id"]


# ---------- ติดตามอัตโนมัติ ----------

def save_watchlist(name, config):
    with connect() as conn:
        return conn.execute("INSERT INTO watchlists (name, created_at, config_json) VALUES (?, ?, ?) RETURNING id",
                            (name, now(), json.dumps(config, ensure_ascii=False))).fetchone()["id"]


def watchlists():
    """[{id, name, created_at, config, last_run}] last_run = รอบล่าสุดของชุดนี้ (หรือ None)"""
    with connect() as conn:
        rows = conn.execute("SELECT * FROM watchlists ORDER BY id").fetchall()
        out = []
        for r in rows:
            last = conn.execute("SELECT id, started_at, changes_json FROM runs WHERE watch_id = ? "
                                "ORDER BY id DESC LIMIT 1", (r["id"],)).fetchone()
            out.append({"id": r["id"], "name": r["name"], "created_at": r["created_at"],
                        "config": json.loads(r["config_json"]),
                        "last_run": {"id": last["id"], "started_at": last["started_at"],
                                     "changes": json.loads(last["changes_json"] or "[]")} if last else None})
    return out


def delete_watchlist(watch_id):
    with connect() as conn:
        conn.execute("DELETE FROM watchlists WHERE id = ?", (watch_id,))


def save_run(started_at, config, snapshot, changes, report_id, watch_id=None):
    with connect() as conn:
        return conn.execute(
            """INSERT INTO runs (watch_id, started_at, config_json, snapshot_json, changes_json, report_id)
               VALUES (?, ?, ?, ?, ?, ?) RETURNING id""",
            (watch_id, started_at, json.dumps(config, ensure_ascii=False),
             json.dumps(snapshot, ensure_ascii=False), json.dumps(changes, ensure_ascii=False), report_id),
        ).fetchone()["id"]


def get_run(run_id):
    with connect() as conn:
        r = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
    if not r:
        return None
    return {"id": r["id"], "watch_id": r["watch_id"], "started_at": r["started_at"],
            "config": json.loads(r["config_json"]), "changes": json.loads(r["changes_json"] or "[]"),
            "report_id": r["report_id"]}


def previous_snapshots(names):
    """{บริษัท: (เวลาที่รอบนั้นเสร็จ, snapshot)} จากรอบล่าสุดที่มีบริษัทนั้น"""
    out = {}
    with connect() as conn:
        rows = conn.execute("SELECT started_at, snapshot_json FROM runs ORDER BY id DESC LIMIT 500").fetchall()
    for r in rows:
        snap = json.loads(r["snapshot_json"] or "{}")
        for name in names:
            if name not in out and name in snap:
                out[name] = (r["started_at"], snap[name])
        if len(out) == len(names):
            break
    return out


# ---------- ข้อมูลภายในที่ผู้ใช้อัปโหลด ----------

def save_internal(rows):
    """rows = [{company, metric, value, unit, period}] แทนค่าเดิมของ (บริษัท, ตัวชี้วัด) เดียวกัน"""
    with connect() as conn:
        conn.executemany(
            """INSERT INTO internal_metrics (company, metric, value, unit, period, uploaded_at)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(company, metric) DO UPDATE SET value = excluded.value, unit = excluded.unit,
                 period = excluded.period, uploaded_at = excluded.uploaded_at""",
            [(r["company"], r["metric"], r["value"], r["unit"], r["period"], now()) for r in rows],
        )


def internal_metrics(names=None):
    with connect() as conn:
        if names is None:
            return _df(conn, "SELECT * FROM internal_metrics ORDER BY company, metric")
        if not names:
            return pd.DataFrame()
        return _df(conn, f"SELECT * FROM internal_metrics WHERE company IN ({_in(names)}) ORDER BY company, metric",
                   list(names))


def clear_internal():
    with connect() as conn:
        conn.execute("DELETE FROM internal_metrics")


def uploaded_documents():
    """PDF ที่อัปโหลดไว้ หนึ่งแถวต่อ (ไฟล์, บริษัท): source_name, company, parts, uploaded_at"""
    with connect() as conn:
        return _df(
            conn,
            """SELECT d.source_name, c.name AS company, COUNT(*) AS parts, MAX(d.fetched_at) AS uploaded_at
               FROM documents d JOIN companies c ON c.id = d.company_id
               WHERE d.source_type = 'document' GROUP BY d.source_name, c.name ORDER BY uploaded_at DESC""")


def delete_uploaded(source_name, company):
    """ลบ PDF ไฟล์นี้ของบริษัทนี้ พร้อมผลจัดหมวดและผลตรวจ คืนจำนวนส่วนที่ลบ"""
    with connect() as conn:
        ids = [r["id"] for r in conn.execute(
            """SELECT d.id FROM documents d JOIN companies c ON c.id = d.company_id
               WHERE d.source_type = 'document' AND d.source_name = ? AND c.name = ?""", (source_name, company))]
        if ids:
            conn.execute(f"DELETE FROM labels WHERE fact_id IN (SELECT id FROM facts WHERE document_id IN ({_in(ids)}))",
                         ids)
            conn.execute(f"DELETE FROM facts WHERE document_id IN ({_in(ids)})", ids)
            conn.execute(f"DELETE FROM documents WHERE id IN ({_in(ids)})", ids)
        return len(ids)


def get_cache(keys, max_age_hours=None):
    """{key: data} จาก market_cache · max_age_hours = ข้ามรายการที่เก่ากว่านี้"""
    if not keys:
        return {}
    with connect() as conn:
        rows = conn.execute(f"SELECT * FROM market_cache WHERE key IN ({_in(keys)})", list(keys)).fetchall()
    out = {}
    for r in rows:
        age = (datetime.now() - datetime.fromisoformat(r["fetched_at"])).total_seconds() / 3600
        if max_age_hours is None or age <= max_age_hours:
            out[r["key"]] = json.loads(r["data_json"])
    return out


def set_cache(key, data):
    with connect() as conn:
        conn.execute("""INSERT INTO market_cache (key, fetched_at, data_json) VALUES (?, ?, ?)
                        ON CONFLICT(key) DO UPDATE SET fetched_at = excluded.fetched_at, data_json = excluded.data_json""",
                     (key, now(), json.dumps(data, ensure_ascii=False)))


# ---------- embeddings (ค้นด้วยความหมายในแท็บถามข้อมูล) ----------
# เวกเตอร์ส่งเข้าออกเป็น bytes ของ float32 · pgvector รับ/คืนเป็นข้อความ "[0.1,0.2,...]"

def _to_vector(vec_bytes):
    return json.dumps(np.frombuffer(vec_bytes, dtype=np.float32).tolist())


def _from_vector(text):
    return np.asarray(json.loads(text), dtype=np.float32).tobytes()


def _by_hash(sql, hashes):
    """รันคำสั่งที่มี {in} กับ hash ทีละ 900 ตัว (SQLite จำกัดจำนวน ? ต่อคำสั่ง)"""
    hashes = list(hashes)
    with connect() as conn:
        for i in range(0, len(hashes), 900):
            part = hashes[i:i + 900]
            yield from conn.execute(sql.format(**{"in": _in(part)}), part).fetchall()


def embedding_hashes(hashes):
    """hash ที่มีเวกเตอร์แล้ว (ไม่โหลดเวกเตอร์)"""
    return {r["hash"] for r in _by_hash("SELECT hash FROM embeddings WHERE hash IN ({in})", hashes)}


def get_embeddings(hashes):
    """{hash: bytes} ของเวกเตอร์ที่เคยคำนวณแล้ว"""
    if has_vector():
        return {r["hash"]: _from_vector(r["vec"])
                for r in _by_hash("SELECT hash, vec::text AS vec FROM embeddings WHERE hash IN ({in})", hashes)}
    return {r["hash"]: bytes(r["vec"]) for r in _by_hash("SELECT hash, vec FROM embeddings WHERE hash IN ({in})", hashes)}


def save_embeddings(vecs, model):
    """vecs = {hash: bytes}"""
    vector = has_vector()
    with connect() as conn:
        conn.executemany(
            f"""INSERT INTO embeddings (hash, model, vec, created_at) VALUES (?, ?, {'?::vector' if vector else '?'}, ?)
                ON CONFLICT(hash) DO UPDATE SET model = excluded.model, vec = excluded.vec,
                  created_at = excluded.created_at""",
            [(h, model, _to_vector(v) if vector else v, now()) for h, v in vecs.items()])


def embedding_scores(query, hashes):
    """{hash: cosine กับ query (bytes)} คิดใน PostgreSQL ด้วย pgvector · None = ไม่มี pgvector ให้คิดด้วย numpy
    คิดทุกรายการที่ส่งมา (ไม่ใช้ index แบบ top-k) เพราะ ask.py ใช้คะแนนของทุกรายการ"""
    if not has_vector():
        return None
    with connect() as conn:
        rows = conn.execute("SELECT hash, 1 - (vec <=> ?::vector) AS sim FROM embeddings WHERE hash = ANY(?)",
                            (_to_vector(query), list(hashes))).fetchall()
    return {r["hash"]: float(r["sim"]) for r in rows}


# ---------- llm_log ----------

def log_llm(key, model, prompt, response, ms):
    with connect() as conn:
        conn.execute("INSERT INTO llm_log (hash, model, prompt, response, ms, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                     (key, model, prompt, response, ms, now()))


def llm_cached(key):
    """คำตอบล่าสุดของ prompt นี้ หรือ None"""
    with connect() as conn:
        row = conn.execute("SELECT response FROM llm_log WHERE hash = ? ORDER BY id DESC LIMIT 1", (key,)).fetchone()
    return row["response"] if row else None


def llm_stats(since=None):
    """{"calls", "seconds"} ของการเรียก LLM จริงตั้งแต่เวลา since (ISO) หรือทั้งหมด"""
    with connect() as conn:
        row = conn.execute("SELECT COUNT(*) AS n, COALESCE(SUM(ms), 0) AS ms FROM llm_log WHERE created_at >= ?",
                           (since or "",)).fetchone()
    return {"calls": int(row["n"]), "seconds": round(int(row["ms"]) / 1000, 1)}  # int: PostgreSQL คืน SUM เป็น Decimal


# ---------- jobs (วิเคราะห์เบื้องหลัง) ----------

def create_job(config, status="running"):
    with connect() as conn:
        return conn.execute("INSERT INTO jobs (status, config_json, log, started_at) VALUES (?, ?, '', ?) RETURNING id",
                            (status, json.dumps(config, ensure_ascii=False), now())).fetchone()["id"]


def claim_job():
    """worker หยิบงาน queued ที่เก่าสุด 1 งานเปลี่ยนเป็น running (คำสั่งเดียว จึงไม่หยิบซ้ำ) คืน id หรือ None
    PostgreSQL: SKIP LOCKED ให้ worker หลายตัวหยิบคนละงานได้โดยไม่รอกัน"""
    lock = " FOR UPDATE SKIP LOCKED" if _pg() else ""
    with connect() as conn:
        row = conn.execute("UPDATE jobs SET status = 'running', started_at = ? WHERE status = 'queued' AND id = "
                           f"(SELECT id FROM jobs WHERE status = 'queued' ORDER BY id LIMIT 1{lock}) RETURNING id",
                           (now(),)).fetchone()
    return row["id"] if row else None


def fail_running_jobs(error):
    """งานที่ค้าง running ตอน worker เริ่มใหม่ (container ถูกรีสตาร์ทกลางงาน) ให้หน้าเว็บรู้ว่าไม่สำเร็จ"""
    with connect() as conn:
        return conn.execute("UPDATE jobs SET status = 'error', error = ?, finished_at = ? WHERE status = 'running'",
                            (error, now())).rowcount


def append_job_log(job_id, line):
    with connect() as conn:
        conn.execute("UPDATE jobs SET log = log || ? WHERE id = ?", (line + "\n", job_id))


def finish_job(job_id, run_id=None, error=None):
    with connect() as conn:
        conn.execute("UPDATE jobs SET status = ?, run_id = ?, error = ?, finished_at = ? WHERE id = ?",
                     ("error" if error else "done", run_id, error, now(), job_id))


def get_job(job_id):
    with connect() as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    if not row:
        return None
    job = dict(row)
    job["config"] = json.loads(job.pop("config_json") or "{}")
    return job


# ---------- labels (ตรวจความแม่น) ----------

_LABEL_COLS = """f.id AS fact_id, c.name AS company, c.business, d.title, d.url, f.summary,
                 f.category, f.sentiment, COALESCE(d.source_type, 'news') AS source_type"""
_LABEL_FROM = """FROM facts f JOIN documents d ON d.id = f.document_id JOIN companies c ON c.id = f.company_id"""


def label_queue(limit=20, company_ids=None):
    """ข่าวที่ยังไม่ได้ตรวจ (เฉพาะข่าวที่ค้นด้วยชื่อ ซึ่งอาจปนเรื่องอื่น) สุ่มลำดับ
    ข่าวที่ระบบตัดออกมีน้อย จึงดึงมาราว 1/3 ของคิว เพื่อให้วัดความแม่นของทั้งสองฝั่งได้
    คืน [{fact_id, company, business, title, url, summary, category, sentiment}]"""
    where = f"AND f.company_id IN ({_in(company_ids)})" if company_ids else ""
    query = f"""SELECT {_LABEL_COLS} {_LABEL_FROM}
                WHERE COALESCE(d.source_type, 'news') IN ('news', 'rss') {where}
                  AND f.id NOT IN (SELECT fact_id FROM labels)
                  AND CASE WHEN f.category = 'irrelevant' THEN 1 ELSE 0 END = ?
                ORDER BY random() LIMIT ?"""
    with connect() as conn:
        dropped = conn.execute(query, [*(company_ids or []), 1, max(limit // 3, 1)]).fetchall()
        kept = conn.execute(query, [*(company_ids or []), 0, limit - len(dropped)]).fetchall()
    rows = [dict(r) for r in dropped + kept]
    random.shuffle(rows)
    return rows


def save_label(fact_id, relevant, category=None, sentiment=None):
    with connect() as conn:
        conn.execute("""INSERT INTO labels (fact_id, relevant, category, sentiment, labeled_at) VALUES (?, ?, ?, ?, ?)
                        ON CONFLICT(fact_id) DO UPDATE SET relevant = excluded.relevant, category = excluded.category,
                          sentiment = excluded.sentiment, labeled_at = excluded.labeled_at""",
                     (fact_id, int(relevant), category, sentiment, now()))


def labels_df():
    """ผลของระบบเทียบกับที่ผู้ใช้ตรวจ หนึ่งแถวต่อข่าวที่ตรวจแล้ว"""
    with connect() as conn:
        return _df(
            conn,
            f"""SELECT {_LABEL_COLS}, l.relevant AS human_relevant, l.category AS human_category,
                       l.sentiment AS human_sentiment, l.labeled_at
                {_LABEL_FROM} JOIN labels l ON l.fact_id = f.id ORDER BY l.labeled_at""")


def label_population():
    """จำนวนข่าวที่ค้นด้วยชื่อทั้งหมด แยกที่ระบบเก็บไว้/ตัดออก (ใช้ประมาณ recall จากตัวอย่าง)"""
    with connect() as conn:
        row = conn.execute(
            f"""SELECT SUM(CASE WHEN f.category != 'irrelevant' THEN 1 ELSE 0 END) AS kept,
                       SUM(CASE WHEN f.category = 'irrelevant' THEN 1 ELSE 0 END) AS dropped
                {_LABEL_FROM} WHERE COALESCE(d.source_type, 'news') IN ('news', 'rss')""").fetchone()
    return {"kept": int(row["kept"] or 0), "dropped": int(row["dropped"] or 0)}


def label_examples(company=None, limit=6):
    """ตัวอย่างที่ผู้ใช้ตรวจแล้วและระบบเคยตัดสินผิด (หรือไม่เกี่ยว) ของบริษัทนี้ก่อน ใช้สอน LLM รอบถัดไป"""
    with connect() as conn:
        rows = conn.execute(
            f"""SELECT c.name AS company, d.title, l.relevant, l.category, l.sentiment,
                       CASE WHEN (f.category = 'irrelevant') != (l.relevant = 0) THEN 1 ELSE 0 END AS wrong_relevance,
                       CASE WHEN l.category IS NOT NULL AND l.category != f.category THEN 1 ELSE 0 END AS wrong_category
                {_LABEL_FROM} JOIN labels l ON l.fact_id = f.id
                WHERE (f.category = 'irrelevant') != (l.relevant = 0) OR l.relevant = 0
                   OR (l.category IS NOT NULL AND l.category != f.category)
                   OR (l.sentiment IS NOT NULL AND l.sentiment != f.sentiment)
                ORDER BY (c.name = ?) DESC, l.labeled_at DESC LIMIT ?""", (company or "", limit)).fetchall()
    return [dict(r) for r in rows]


# ---------- ดูแลข้อมูล ----------

def duplicate_groups():
    """บริษัทที่ชื่อหุ้นเดียวกันแต่เป็นคนละแถว (เช่น True / True Corporation / ทรู)
    คืน [[{name, set_symbol, docs}, ...], ...] เรียงแถวที่มีข้อมูลมากสุดก่อน"""
    with connect() as conn:
        rows = conn.execute(
            """SELECT c.name, c.set_symbol, COUNT(d.id) AS docs FROM companies c
               LEFT JOIN documents d ON d.company_id = c.id
               WHERE c.set_symbol IS NOT NULL AND c.set_symbol != ''
               GROUP BY c.id ORDER BY c.set_symbol, docs DESC""").fetchall()
    groups = {}
    for r in rows:
        groups.setdefault(r["set_symbol"], []).append(dict(r))
    return [g for g in groups.values() if len(g) > 1]


def merge_companies(keep, others):
    """ย้ายข้อมูลของ others มาไว้ที่ keep แล้วลบแถว others · ข่าวที่ซ้ำกับของ keep (url หรือหัวข้อเดียวกัน) ถูกทิ้ง
    ชื่อของ others ถูกเพิ่มเป็นชื่อเรียกของ keep · คืนจำนวนรายการที่ย้าย"""
    others = [o for o in others if o != keep]
    if not others:
        return 0
    keep_row = get_companies([keep])[0]
    moved = 0
    with connect() as conn:
        keep_id = conn.execute("SELECT id FROM companies WHERE name = ?", (keep,)).fetchone()["id"]
        for name in others:
            row = conn.execute("SELECT id FROM companies WHERE name = ?", (name,)).fetchone()
            if not row:
                continue
            oid = row["id"]
            dup = [r["id"] for r in conn.execute(
                """SELECT d.id FROM documents d WHERE d.company_id = ? AND EXISTS (
                     SELECT 1 FROM documents k WHERE k.company_id = ? AND (k.url = d.url OR k.title = d.title))""",
                (oid, keep_id))]
            if dup:
                conn.execute(f"DELETE FROM labels WHERE fact_id IN (SELECT id FROM facts WHERE document_id IN ({_in(dup)}))",
                             dup)
                conn.execute(f"DELETE FROM facts WHERE document_id IN ({_in(dup)})", dup)
                conn.execute(f"DELETE FROM documents WHERE id IN ({_in(dup)})", dup)
            moved += conn.execute("UPDATE documents SET company_id = ? WHERE company_id = ?", (keep_id, oid)).rowcount
            conn.execute("UPDATE facts SET company_id = ? WHERE company_id = ?", (keep_id, oid))
            if conn.execute("SELECT 1 FROM financials WHERE company_id = ?", (keep_id,)).fetchone():
                conn.execute("DELETE FROM financials WHERE company_id = ?", (oid,))
            else:
                conn.execute("UPDATE financials SET company_id = ? WHERE company_id = ?", (keep_id, oid))
            # ตัวชี้วัดที่ keep มีอยู่แล้วไม่ย้าย (ใช้ค่าของ keep) แถวที่เหลือของ name ถูกลบในบรรทัดถัดไป
            conn.execute("""UPDATE internal_metrics SET company = ? WHERE company = ?
                            AND metric NOT IN (SELECT metric FROM internal_metrics WHERE company = ?)""",
                         (keep, name, keep))
            conn.execute("DELETE FROM internal_metrics WHERE company = ?", (name,))
            conn.execute("DELETE FROM companies WHERE id = ?", (oid,))
        aliases = keep_row["aliases"] + [o for o in others if o not in keep_row["aliases"]]
        conn.execute("UPDATE companies SET aliases = ? WHERE id = ?", (json.dumps(aliases, ensure_ascii=False), keep_id))
    return moved


def checked_relevance_count(company_ids):
    """(ข่าวที่ค้นด้วยชื่อทั้งหมด, ที่ผู้ใช้ตรวจแล้ว) ของบริษัทเหล่านี้"""
    with connect() as conn:
        row = conn.execute(
            f"""SELECT COUNT(*) AS n, COUNT(l.fact_id) AS labeled FROM facts f
                JOIN documents d ON d.id = f.document_id LEFT JOIN labels l ON l.fact_id = f.id
                WHERE f.company_id IN ({_in(company_ids)}) AND COALESCE(d.source_type, 'news') IN ('news', 'rss')""",
            company_ids).fetchone()
    return row["n"], row["labeled"]


def reset_news_facts(company_ids):
    """ลบผลจัดหมวดของข่าวที่ค้นด้วยชื่อ (ยกเว้นข่าวที่ผู้ใช้ตรวจแล้ว) เพื่อให้ LLM จัดหมวดและตรวจความเกี่ยวข้องใหม่"""
    with connect() as conn:
        return conn.execute(
            f"""DELETE FROM facts WHERE company_id IN ({_in(company_ids)})
                AND id NOT IN (SELECT fact_id FROM labels)
                AND document_id IN (SELECT id FROM documents WHERE COALESCE(source_type, 'news') IN ('news', 'rss'))""",
            company_ids).rowcount
