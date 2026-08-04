from dbxstats.config import Settings


def test_defaults_roundtrip():
    d = Settings().as_dict()
    assert Settings.from_dict(d).as_dict() == d


def test_unknown_keys_ignored():
    s = Settings.from_dict({"foo": "bar", "accent": "green"})
    assert s.accent == "green"
    assert not hasattr(s, "foo")


def test_accent_fallback():
    assert Settings.from_dict({"accent": "neon"}).accent == "cyan"


def test_start_view_fallback():
    assert Settings.from_dict({"start_view": "nope"}).start_view == "dashboard"


def test_interval_snaps_to_nearest():
    assert Settings.from_dict({"update_interval": 0.9}).update_interval == 1.0
    assert Settings.from_dict({"update_interval": 0.3}).update_interval == 0.25


def test_fps_window_snaps():
    assert Settings.from_dict({"fps_window": 45.0}).fps_window == 30.0
    assert Settings.from_dict({"fps_window": 55.0}).fps_window == 60.0


def test_window_size_clamped():
    s = Settings.from_dict({"win_w": 100, "win_h": 99999})
    assert s.win_w == 900
    assert s.win_h == 4000


def test_ui_scale_clamped():
    assert Settings.from_dict({"ui_scale": 9.0}).ui_scale == 1.8
    assert Settings.from_dict({"ui_scale": 0.1}).ui_scale == 0.8


def test_overlay_metrics_filtered():
    s = Settings.from_dict({"overlay_metrics": ["fps", "lixo", "cpu"]})
    assert s.overlay_metrics == ["fps", "cpu"]


def test_overlay_metrics_never_empty():
    assert Settings.from_dict({"overlay_metrics": ["lixo"]}).overlay_metrics


def test_dash_cards_filtered():
    s = Settings.from_dict({"dash_cards": ["cpu", "inexistente"]})
    assert s.dash_cards == ["cpu"]


def test_alert_clamped():
    s = Settings.from_dict({"alert_cpu_temp": 500, "alert_ram_pct": -5})
    assert s.alert_cpu_temp == 120
    assert s.alert_ram_pct == 0


def test_ping_host_fallback():
    assert Settings.from_dict({"ping_host": "   "}).ping_host == "8.8.8.8"


def test_corner_fallback():
    assert Settings.from_dict({"overlay_corner": "meio"}).overlay_corner == "top-left"
