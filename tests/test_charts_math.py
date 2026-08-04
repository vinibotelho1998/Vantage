"""Funcoes puras dos graficos: suavizacao, downsample e escala."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from dbxstats.ui.charts import envelope, monotone_tangents, nice_step  # noqa: E402


def test_tangents_flat_series_is_flat():
    assert monotone_tangents([5.0] * 6) == [0.0] * 6


def test_tangents_do_not_overshoot_local_extremes():
    ys = [0.0, 10.0, 0.0]
    m = monotone_tangents(ys)
    assert m[1] == 0.0  # pico vira tangente zero: a curva nao passa de 10


def test_tangents_monotone_series_keeps_direction():
    m = monotone_tangents([0.0, 1.0, 2.0, 3.0])
    assert all(v >= 0 for v in m)


def test_envelope_passthrough_when_small():
    assert envelope([1.0, 2.0, 3.0], 100) == [(1.0, 1.0, 1.0), (2.0, 2.0, 2.0),
                                              (3.0, 3.0, 3.0)]


def test_envelope_downsamples_to_columns():
    data = [float(i) for i in range(1000)]
    out = envelope(data, 50)
    assert len(out) == 50
    assert out[0][0] == 0.0
    assert out[-1][1] == 999.0


def test_envelope_preserves_spikes():
    data = [1.0] * 999
    data[500] = 99.0
    out = envelope(data, 20)
    assert max(hi for _lo, hi, _avg in out) == 99.0


def test_envelope_empty():
    assert envelope([], 10) == []


def test_nice_step_rounds_up():
    assert nice_step(100) == 25.0
    assert nice_step(1000) == 250.0
    assert nice_step(0) == 1.0
