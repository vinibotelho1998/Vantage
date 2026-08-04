import math

from dbxstats.core.series import Accumulator, Ema, History, Series, mean, percentile, stdev


def test_percentile_bounds():
    data = [float(i) for i in range(101)]
    assert percentile(data, 0.0) == 0.0
    assert percentile(data, 1.0) == 100.0
    assert percentile(data, 0.5) == 50.0


def test_percentile_interpolates():
    assert percentile([0.0, 10.0], 0.5) == 5.0


def test_percentile_empty_is_nan():
    assert math.isnan(percentile([], 0.5))


def test_mean_and_stdev():
    assert mean([2, 4, 6]) == 4
    assert stdev([5, 5, 5]) == 0.0
    assert stdev([1]) == 0.0


def test_series_ring_and_last():
    s = Series(maxlen=3)
    for v in (1, 2, 3, 4):
        s.push(v)
    assert s.values() == [2.0, 3.0, 4.0]
    assert s.last == 4.0


def test_series_none_becomes_nan_and_last_skips_it():
    s = Series(maxlen=4)
    s.push(10)
    s.push(None)
    assert math.isnan(s.values()[1])
    assert s.last == 10.0
    assert s.finite() == [10.0]


def test_series_resize_keeps_recent():
    s = Series(maxlen=5)
    for v in range(5):
        s.push(v)
    s.resize(2)
    assert s.values() == [3.0, 4.0]


def test_history_resize_all_series():
    h = History(maxlen=4)
    for v in range(4):
        h.push("a", v)
        h.push("b", v)
    h.resize(2)
    assert len(h.values("a")) == 2
    assert len(h.values("b")) == 2


def test_history_unknown_key_is_empty():
    assert History().values("nada") == []


def test_accumulator_min_avg_max():
    acc = Accumulator()
    for v in (10, 20, 30):
        acc.update("k", v)
    assert acc.get("k") == (10.0, 20.0, 30.0)
    assert acc.last("k") == 30.0
    assert acc.count("k") == 3


def test_accumulator_ignores_none_and_text():
    acc = Accumulator()
    acc.update("k", None)
    acc.update("k", "x")
    acc.update("k", float("nan"))
    assert acc.get("k") is None


def test_accumulator_fmt():
    acc = Accumulator()
    acc.update("k", 10)
    acc.update("k", 20)
    assert acc.fmt("k", 0, "%") == "mín 10 · méd 15 · máx 20%"
    assert acc.fmt("desconhecida") == ""


def test_accumulator_clear_single_key():
    acc = Accumulator()
    acc.update("a", 1)
    acc.update("b", 2)
    acc.clear("a")
    assert acc.get("a") is None
    assert acc.get("b") is not None


def test_ema_converges():
    ema = Ema(0.5)
    ema.push(0)
    ema.push(10)
    assert ema.value == 5.0
    ema.push(None)
    assert ema.value == 5.0
