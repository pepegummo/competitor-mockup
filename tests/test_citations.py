from core.analyze import link_refs

REFS = [(f"ข่าว {i}", f"https://n/{i}") for i in range(1, 13)]


def test_single_and_list():
    out = link_refs("AIS โต [1] และ True ลด [2, 3]", REFS)
    assert "[[1]](https://n/1)" in out
    assert "[[2]](https://n/2)[[3]](https://n/3)" in out


def test_range_and_llm_styles():
    out = link_refs("ข่าวหลายข่าว [6-8] และ [Table C: ref 11-12] และ [ref 4]", REFS)
    for n in (6, 7, 8, 11, 12, 4):
        assert f"[[{n}]](https://n/{n})" in out


def test_table_names_removed():
    out = link_refs("กำไรดี [Table F] อันดับดี [Sector ranks] และ [Financials]", REFS)
    assert "Table F" not in out and "Sector ranks" not in out and "Financials" not in out


def test_reference_list_only_used():
    out = link_refs("อ้าง [2] เท่านั้น", REFS)
    tail = out.split("**แหล่งอ้างอิง**")[1]
    assert "2. [ข่าว 2](https://n/2)" in tail
    assert "1. [" not in tail


def test_out_of_range_left_alone():
    out = link_refs("ไม่มีข่าวนี้ [99]", REFS)
    assert "[99]" in out and "แหล่งอ้างอิง" not in out
