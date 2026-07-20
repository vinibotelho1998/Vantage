from dbxstats.stats import StatsTracker


def test_min_avg_max():
    s = StatsTracker()
    for v in (10, 20, 30):
        s.update("k", v)
    assert s.get("k") == (10, 20, 30)


def test_ignores_none_and_nonnumeric():
    s = StatsTracker()
    s.update("k", None)
    s.update("k", "x")
    assert s.get("k") is None
    s.update("k", 5)
    assert s.get("k") == (5, 5, 5)


def test_fmt():
    s = StatsTracker()
    s.update("k", 10)
    s.update("k", 20)
    assert s.fmt("k", 0, "%") == "mín 10 · méd 15 · máx 20%"


def test_fmt_unknown_key_is_empty():
    assert StatsTracker().fmt("nope") == ""


def test_clear():
    s = StatsTracker()
    s.update("k", 1)
    s.clear()
    assert s.get("k") is None
