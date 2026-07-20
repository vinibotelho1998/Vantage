from dbxstats.ui.benchmark import summarize


def test_summarize_smooth():
    s = summarize([10.0] * 100)
    assert s["frames"] == 100
    assert round(s["fps_avg"]) == 100
    assert s["stutter_pct"] == 0
    assert s["hitches"] == 0


def test_summarize_detects_hitch():
    s = summarize([10.0] * 99 + [120.0])
    assert s["ft_max"] == 120.0
    assert s["hitches"] >= 1


def test_summarize_too_few_frames():
    assert summarize([5.0, 6.0, 7.0]) is None
