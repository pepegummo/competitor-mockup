"""ย้ายข้อมูลจาก SQLite (data/app.db) ไป PostgreSQL ครั้งเดียว · ต้องตั้ง DATABASE_URL (ใน .env หรือ environment)
    python migrate_to_postgres.py                    ย้ายจาก data/app.db
    python migrate_to_postgres.py /app/data/app.db   ระบุไฟล์ (ใน docker: docker compose exec worker python migrate_to_postgres.py)
id เดิมถูกเก็บไว้ ผลวิเคราะห์ที่เปิดค้าง (last_run.json) และรายงานที่อ้างเลขรอบยังเปิดได้
ทำใน transaction เดียว: พังกลางทางไม่มีข้อมูลค้างครึ่ง ๆ · ถ้า PostgreSQL มีบริษัทอยู่แล้วจะไม่ย้าย (กันข้อมูลซ้ำ)"""
import argparse
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from core import db  # noqa: E402

# ตารางแม่ก่อนตารางลูก · เงื่อนไขตัดแถวที่ชี้ไปแถวที่ไม่มีอยู่แล้ว (PostgreSQL ไม่ยอมให้ใส่ ส่วน SQLite เก่าอาจมีหลงเหลือ)
TABLES = [
    ("companies", ""),
    ("documents", "company_id IN (SELECT id FROM companies)"),
    ("facts", "document_id IN (SELECT id FROM documents) AND company_id IN (SELECT id FROM companies)"),
    ("labels", "fact_id IN (SELECT id FROM facts WHERE document_id IN (SELECT id FROM documents))"),
    ("financials", "company_id IN (SELECT id FROM companies)"),
    ("reports", ""), ("company_groups", ""), ("watchlists", ""), ("runs", ""), ("internal_metrics", ""),
    ("llm_log", ""), ("jobs", ""), ("market_cache", ""), ("embeddings", ""),
]
SERIAL = ["companies", "documents", "facts", "reports", "watchlists", "runs", "llm_log", "jobs"]
BATCH = 1000


def sqlite_columns(src, table):
    return [r[1] for r in src.execute(f"PRAGMA table_info({table})")]


def pg_columns(conn, table):
    return {r["column_name"] for r in conn.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_schema = current_schema() AND table_name = ?",
        (table,))}


def copy_table(src, conn, table, where, vector):
    """คืน (แถวใน SQLite, แถวที่ส่งไป PostgreSQL)"""
    have = sqlite_columns(src, table)
    if not have:
        return 0, 0  # SQLite รุ่นเก่ายังไม่มีตารางนี้
    cols = [c for c in have if c in pg_columns(conn, table)]
    total = src.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    marks = ", ".join("?::vector" if vector and table == "embeddings" and c == "vec" else "?" for c in cols)
    sql = f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({marks}) ON CONFLICT DO NOTHING"
    vec_at = cols.index("vec") if table == "embeddings" and "vec" in cols else None
    cur = src.execute(f"SELECT {', '.join(cols)} FROM {table}" + (f" WHERE {where}" if where else ""))
    sent = 0
    while rows := cur.fetchmany(BATCH):
        rows = [list(r) for r in rows]
        if vec_at is not None:
            for r in rows:
                r[vec_at] = db._to_vector(r[vec_at]) if vector else bytes(r[vec_at])
        conn.executemany(sql, rows)
        sent += len(rows)
    return total, sent


def main():
    parser = argparse.ArgumentParser(description="ย้ายข้อมูลจาก SQLite ไป PostgreSQL (ครั้งเดียว)")
    parser.add_argument("sqlite", nargs="?", default=str(db.DB_PATH), help="ไฟล์ SQLite (ค่าเริ่ม data/app.db)")
    args = parser.parse_args()
    if not db.DATABASE_URL:
        sys.exit("ยังไม่ได้ตั้ง DATABASE_URL (postgresql://...) ใน .env หรือ environment")
    path = Path(args.sqlite).resolve()
    if not path.exists():
        sys.exit(f"ไม่พบไฟล์ {path}")

    db.init_db()
    if db.count_rows("companies"):
        sys.exit("PostgreSQL มีข้อมูลบริษัทอยู่แล้ว ไม่ย้ายซ้ำ (ถ้าต้องการย้ายใหม่ ให้ลบข้อมูลใน PostgreSQL ก่อน)")
    vector = db.has_vector()
    src = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)  # อ่านอย่างเดียว ไม่แก้ไฟล์ต้นทาง
    print(f"ย้ายจาก {path} → PostgreSQL" + (" (เวกเตอร์เก็บเป็น pgvector)" if vector else " (ไม่มี pgvector: เวกเตอร์เก็บเป็น bytes)"))
    counts = {}
    with db.connect() as conn:
        for table, where in TABLES:
            counts[table] = copy_table(src, conn, table, where, vector)
        for table in SERIAL:  # เลขรันต่อจาก id สูงสุดที่ย้ายมา ไม่งั้นแถวใหม่จะชน id เดิม
            conn.execute(f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), COALESCE(MAX(id), 1), "
                         f"MAX(id) IS NOT NULL) FROM {table}")
    src.close()

    print(f"{'ตาราง':<18}{'SQLite':>9}{'PostgreSQL':>12}")
    skipped = False
    for table, (total, sent) in counts.items():
        now = db.count_rows(table)
        note = f"  (ข้าม {total - sent} แถวที่ชี้ไปข้อมูลที่ไม่มีแล้ว)" if sent < total else ""
        skipped |= now != total
        print(f"{table:<18}{total:>9}{now:>12}{note}")
    print("เสร็จ" + (" · บางตารางจำนวนไม่เท่ากัน ดูหมายเหตุด้านบน" if skipped else " · จำนวนแถวตรงกันทุกตาราง"))


if __name__ == "__main__":
    main()
