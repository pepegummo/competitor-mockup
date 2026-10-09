from core import benchmark


def seed(tmp_db):
    tmp_db.set_cache("grp:AAA", {"group": "COMM", "name": "พาณิชย์", "peers": ["AAA", "BBB", "CCC", "DDD"]})
    rows = {"AAA": (20.0, 0.5), "BBB": (10.0, 1.0), "CCC": (5.0, 2.0), "DDD": (-1.0, 3.0)}
    for symbol, (margin, de) in rows.items():
        tmp_db.set_cache(f"hl:{symbol}", {"symbol": symbol, "net_margin_pct": margin, "de_ratio": de})


def test_rank_and_median(tmp_db):
    seed(tmp_db)
    tb = benchmark.table({"บริษัท A": "AAA"}).set_index("metric")
    assert tb.loc["net_margin_pct", "rank"] == 1 and tb.loc["net_margin_pct", "n"] == 4
    assert tb.loc["net_margin_pct", "median"] == 7.5
    assert tb.loc["de_ratio", "rank"] == 1  # หนี้ต่ำสุด = อันดับดีสุด


def test_percentiles_right_is_better(tmp_db):
    seed(tmp_db)
    df = benchmark.frames(["AAA"])["AAA"]["df"]
    pct = benchmark.percentiles(df)
    assert pct.loc["AAA", "net_margin_pct"] == 100 and pct.loc["AAA", "de_ratio"] == 100
    assert pct.loc["DDD", "de_ratio"] == 25


def test_highlights_names_best_and_weak(tmp_db):
    seed(tmp_db)
    tmp_db.set_cache("grp:DDD", tmp_db.get_cache(["grp:AAA"])["grp:AAA"])
    lines = benchmark.highlights(benchmark.table({"บริษัท D": "DDD"}))
    assert len(lines) == 1 and "จุดอ่อน" in lines[0]
