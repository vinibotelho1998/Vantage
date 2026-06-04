from dbxstats.config import Settings


def test_defaults_roundtrip():
    d = Settings().as_dict()
    assert Settings.from_dict(d).as_dict() == d


def test_sanitize_clamps_opacity():
    assert Settings.from_dict({"opacity": 5.0}).opacity == 1.0
    assert Settings.from_dict({"opacity": 0.0}).opacity == 0.4


def test_position_fallback():
    assert Settings.from_dict({"position": "weird"}).position == "bottom-right"


def test_unknown_keys_ignored():
    s = Settings.from_dict({"foo": "bar", "accent": "green"})
    assert s.accent == "green"
    assert not hasattr(s, "foo")


def test_interval_snaps_to_nearest():
    assert Settings.from_dict({"update_interval": 0.9}).update_interval == 1.0


def test_fps_metrics_filtered():
    assert Settings.from_dict({"fps_metrics": ["inst", "garbage"]}).fps_metrics == ["inst"]


def test_accent_fallback():
    assert Settings.from_dict({"accent": "neon"}).accent == "blue"


def test_overlay_corner_fallback():
    assert Settings.from_dict({"overlay_corner": "middle"}).overlay_corner == "top-left"
