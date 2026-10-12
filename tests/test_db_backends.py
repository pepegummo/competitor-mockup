"""คำสั่ง SQL ที่ต่างกันระหว่าง SQLite กับ PostgreSQL (upsert, RETURNING, boolean, NUL, pgvector) และสคริปต์ย้ายข้อมูล
รันกับ SQLite เสมอ · ตั้ง TEST_DATABASE_URL แล้วรันซ้ำเพื่อเทสกับ PostgreSQL"""
import sqlite3
import sys
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pytest

from tests.conftest import TEST_DATABASE_URL, reset_pg


def add_news(db, company, titles, category="news_pr"):
    cid = db.upsert_company(company)
    for i, t in enumerate(titles):
        db.insert_document(cid, "news", f"https://x/{company}/{i}", t, "2026-10-01", f"{company}-{i}", "")
    for d in db.unprocessed_documents([cid]):
        db.insert_fact(d["id"], cid, category, "neutral", d["title"])
    return cid


def test_insert_once_and_upsert(tmp_db):
    cid = tmp_db.upsert_company("AIS", website="https://ais.th")
    assert tmp_db.upsert_company("AIS", role="self") == cid
    assert tmp_db.get_companies(["AIS"])[0]["website"] == "https://ais.th"  # ค่าว่างไม่ทับค่าเดิม
    assert tmp_db.insert_document(cid, "news", "u", "t", "2026-10-01", "h1", "") is True
    assert tmp_db.insert_document(cid, "news", "u", "t", "2026-10-01", "h1", "") is False
    tmp_db.set_cache("k", {"v": 1})
    tmp_db.set_cache("k", {"v": 2})
    assert tmp_db.get_cache(["k"]) == {"k": {"v": 2}}


def test_returning_ids_increase(tmp_db):
    first, second = tmp_db.save_report("phase1", "a"), tmp_db.save_report("phase1", "b")
    assert second > first
    assert tmp_db.get_report(second)["content_md"] == "b"
    run = tmp_db.save_run(tmp_db.now(), {}, {"A": {"n": 1}}, [], second)
    assert tmp_db.get_run(run)["report_id"] == second
    assert tmp_db.save_watchlist("ชุด", {"companies": ["A"]}) > 0


def test_nul_and_numpy_values(tmp_db):
    cid = tmp_db.upsert_company("NT")
    assert tmp_db.insert_document(cid, "news", "u", "ข่าว\x00เสีย", "2026-10-01", "h", "", content="a\x00b")
    tmp_db.save_internal([{"company": "NT", "metric": "NPS", "value": np.float64(41.5), "unit": "", "period": ""}])
    assert tmp_db.internal_metrics(["NT"])["value"].tolist() == [41.5]


def test_labels_and_population(tmp_db):
    cid = add_news(tmp_db, "True", ["ข่าว 1", "ข่าว 2", "ข่าว 3"])
    add_news(tmp_db, "Other", ["ไม่เกี่ยว"], category="irrelevant")
    assert tmp_db.label_population() == {"kept": 3, "dropped": 1}
    queue = tmp_db.label_queue(limit=6)
    assert len(queue) == 4 and sum(r["category"] == "irrelevant" for r in queue) == 1
    fact = next(r["fact_id"] for r in queue if r["company"] == "True")
    tmp_db.save_label(fact, False)
    tmp_db.save_label(fact, True, "promotion", "positive")  # ตรวจซ้ำ = แทนค่าเดิม
    labels = tmp_db.labels_df()
    assert len(labels) == 1 and labels["human_category"].tolist() == ["promotion"]
    assert tmp_db.checked_relevance_count([cid]) == (3, 1)
    assert all(r["wrong_relevance"] in (0, 1) for r in tmp_db.label_examples("True"))


def test_merge_keeps_existing_metric(tmp_db):
    add_news(tmp_db, "True", ["โปรใหม่"])
    add_news(tmp_db, "ทรู", ["โปรใหม่", "ข่าวอื่น"])
    tmp_db.save_internal([{"company": "True", "metric": "NPS", "value": 40, "unit": "", "period": ""},
                          {"company": "ทรู", "metric": "NPS", "value": 10, "unit": "", "period": ""},
                          {"company": "ทรู", "metric": "ลูกค้าใหม่", "value": 5, "unit": "", "period": ""}])
    assert tmp_db.merge_companies("True", ["ทรู"]) == 1  # ข่าวหัวข้อซ้ำถูกทิ้ง ย้ายแค่ "ข่าวอื่น"
    m = tmp_db.internal_metrics().set_index("metric")["value"]
    assert m.to_dict() == {"NPS": 40, "ลูกค้าใหม่": 5}
    assert tmp_db.company_names() == ["True"]


def test_claim_job_from_many_threads_never_duplicates(tmp_db):
    jobs = [tmp_db.create_job({"i": i}, status="queued") for i in range(8)]
    with ThreadPoolExecutor(4) as pool:
        claimed = list(pool.map(lambda _: tmp_db.claim_job(), range(12)))
    assert sorted(j for j in claimed if j) == jobs


def test_embedding_scores_match_numpy(tmp_db):
    rng = np.random.default_rng(0)
    vecs = rng.normal(size=(5, 8)).astype(np.float32)
    vecs /= np.linalg.norm(vecs, axis=1, keepdims=True)
    hashes = [f"h{i}" for i in range(5)]
    tmp_db.save_embeddings({h: v.tobytes() for h, v in zip(hashes, vecs)}, "m")
    assert tmp_db.embedding_hashes(hashes + ["ไม่มี"]) == set(hashes)
    assert tmp_db.get_embeddings(["h2"])["h2"] == vecs[2].tobytes()
    scores = tmp_db.embedding_scores(vecs[0].tobytes(), hashes)
    if not TEST_DATABASE_URL:
        assert scores is None  # SQLite: embed.py คิดด้วย numpy เอง
        return
    assert tmp_db.has_vector()
    assert np.allclose([scores[h] for h in hashes], vecs @ vecs[0], atol=1e-5)


@pytest.mark.skipif(not TEST_DATABASE_URL, reason="ต้องตั้ง TEST_DATABASE_URL")
def test_migrate_sqlite_to_postgres(tmp_path, monkeypatch):
    import migrate_to_postgres
    from core import db
    monkeypatch.setattr(db, "DATA_DIR", tmp_path)
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "app.db")
    monkeypatch.setattr(db, "DATABASE_URL", "")
    db.init_db()
    add_news(db, "AIS", ["ข่าว 1", "ข่าว 2"])
    report = db.save_report("phase1", "รายงาน")
    db.save_embeddings({"h": np.full(4, 0.5, dtype=np.float32).tobytes()}, "m")
    with sqlite3.connect(tmp_path / "app.db") as conn:  # ข้อมูลหลงเหลือจาก SQLite เก่า: fact ที่ไม่มีข่าวแล้ว
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute("INSERT INTO facts (document_id, company_id, category) VALUES (999, 1, 'other')")

    monkeypatch.setattr(db, "DATABASE_URL", TEST_DATABASE_URL)
    reset_pg(TEST_DATABASE_URL)
    monkeypatch.setattr(sys, "argv", ["migrate_to_postgres.py", str(tmp_path / "app.db")])
    migrate_to_postgres.main()
    assert db.count_rows("documents") == 2 and db.count_rows("facts") == 2  # fact ที่ชี้ข่าวที่ไม่มีถูกข้าม
    assert db.get_report(report)["content_md"] == "รายงาน"  # id เดิม
    assert db.save_report("phase1", "ใหม่") == report + 1  # เลขรันต่อจากที่ย้ายมา
    assert db.get_embeddings(["h"])["h"] == np.full(4, 0.5, dtype=np.float32).tobytes()
    with pytest.raises(SystemExit):
        migrate_to_postgres.main()  # ย้ายซ้ำไม่ได้
