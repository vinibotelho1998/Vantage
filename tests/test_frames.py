import math

from dbxstats.core import frames as fr

NAN = float("nan")


def make(frametimes, cpu=NAN, gpu=NAN, displayed=1.0):
    """Constroi amostras no formato do motor a partir de uma lista de frametimes."""
    out = []
    t = 0.0
    for ms in frametimes:
        t += ms / 1000.0
        out.append((t, ms, cpu, gpu, gpu, 10.0, displayed, NAN))
    return out


def test_empty_metrics():
    m = fr.compute([])
    assert m.frames == 0
    assert m.fps_avg is None


def test_steady_60fps():
    m = fr.compute(make([16.667] * 600))
    assert round(m.fps_avg) == 60
    assert round(m.low_1) == 60
    assert m.stutter_pct == 0.0
    assert m.hitches == 0
    assert m.consistency == 100.0


def test_lows_are_worse_than_average():
    frametimes = [8.0] * 990 + [40.0] * 10
    m = fr.compute(make(frametimes))
    assert m.low_1 < m.fps_avg
    assert m.low_01 <= m.low_1
    assert round(m.low_1) == 25  # media dos 1% piores = 40 ms


def test_percentile_variants_present():
    m = fr.compute(make([8.0] * 950 + [30.0] * 50))
    assert m.p1 is not None and m.p01 is not None
    assert m.p1 < m.fps_avg
    assert m.p01 <= m.p1


def test_hitch_detection():
    m = fr.compute(make([8.0] * 200 + [120.0]))
    assert m.hitches == 1
    assert m.stutter_pct > 0
    assert m.ft_max == 120.0


def test_dropped_frames_counted():
    samples = make([8.0] * 100)
    samples = [s[:6] + (NAN,) + s[7:] for s in samples[:10]] + samples[10:]
    m = fr.compute(samples)
    assert m.dropped_pct == 10.0


def test_bottleneck_gpu():
    m = fr.compute(make([10.0] * 300, cpu=4.0, gpu=9.8))
    assert m.bottleneck == "GPU"


def test_bottleneck_cpu():
    m = fr.compute(make([10.0] * 300, cpu=9.7, gpu=3.0))
    assert m.bottleneck == "CPU"


def test_bottleneck_capped():
    m = fr.compute(make([10.0] * 300, cpu=3.0, gpu=4.0))
    assert "Limitado" in m.bottleneck


def test_bottleneck_unknown_without_columns():
    m = fr.compute(make([10.0, 11.0, 9.0] * 50))
    assert m.bottleneck == "—"


def test_window_slices_by_time():
    samples = make([10.0] * 1000)          # 10 s no total
    recent = fr.window(samples, 1.0)
    assert 95 <= len(recent) <= 105


def test_window_noop_when_shorter():
    samples = make([10.0] * 10)
    assert fr.window(samples, 60.0) == samples


def test_fps_now_uses_recent_window():
    samples = make([20.0] * 500 + [5.0] * 200)   # acelera no fim
    m = fr.compute(samples, now_window=1.0)
    assert m.fps_now > m.fps_avg


def test_smoothness_penalises_stutter():
    smooth = fr.compute(make([8.0] * 1000))
    rough = fr.compute(make(([8.0] * 90 + [30.0] * 10) * 10))
    assert smooth.smoothness > rough.smoothness


def test_histogram_shape():
    centers, counts = fr.histogram([8.0] * 100 + [16.0] * 100, bins=10)
    assert len(centers) == len(counts) == 10
    assert sum(counts) == 200


def test_histogram_needs_data():
    assert fr.histogram([]) == ([], [])


def test_percentile_curve_monotonic():
    curve = fr.percentile_curve([8.0 + i * 0.01 for i in range(500)])
    assert len(curve) > 10
    fps = [v for _q, v in curve]
    assert fps == sorted(fps)


def test_verdict_changes_with_quality():
    good = fr.verdict(fr.compute(make([8.0] * 1000)))
    bad = fr.verdict(fr.compute(make(([8.0] * 70 + [60.0] * 30) * 10)))
    assert good != bad
    assert fr.verdict(fr.FrameMetrics()) == "Sem dados de frame."


def test_metrics_serialisable():
    m = fr.compute(make([10.0] * 100))
    d = m.as_dict()
    assert d["frames"] == 100
    assert not any(isinstance(v, float) and math.isnan(v)
                   for v in d.values() if isinstance(v, float))
