from collections import deque

from dbxstats.sensors.fps import _calc_fps
from dbxstats.sensors.gpu import _parse_smi_watts
from dbxstats.ui.fps_graph import _p95, _resample


def test_calc_fps_empty_uses_fallback():
    assert _calc_fps(deque(), 10.0) == 100


def test_calc_fps_average():
    dq = deque([(0, 16.6), (1, 16.6), (2, 16.6)])
    assert _calc_fps(dq, 16.6) == 60


def test_calc_fps_zero_fallback():
    assert _calc_fps(deque(), 0.0) == 0


def test_parse_smi_watts_number():
    assert _parse_smi_watts("123.4\n") == 123.4


def test_parse_smi_watts_comma_decimal():
    assert _parse_smi_watts("99,5 W\n") == 99.5


def test_parse_smi_watts_unsupported():
    assert _parse_smi_watts("[N/A]\n") is None
    assert _parse_smi_watts("[Not Supported]") is None


def test_resample_downsamples():
    assert len(_resample(list(range(1000)), 100)) == 100


def test_resample_passthrough_when_small():
    assert _resample([1, 2, 3], 100) == [1, 2, 3]


def test_p95_high():
    assert _p95(list(range(100))) >= 90
