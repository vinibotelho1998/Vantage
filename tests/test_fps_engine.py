"""Testa o parsing do CSV do PresentMon e a agregacao, sem subir processo nenhum."""
import math

from dbxstats.sensors import fps as fpsmod
from dbxstats.sensors.fps import FpsEngine, _Layout

HEADER_V2 = ("Application,ProcessID,SwapChainAddress,PresentRuntime,SyncInterval,"
             "PresentFlags,AllowsTearing,PresentMode,CPUStartTime,FrameTime,CPUBusy,"
             "CPUWait,GPULatency,GPUTime,GPUBusy,GPUWait,DisplayLatency,DisplayedTime,"
             "AnimationError,AnimationTime,MsFlipDelay,AllInputToPhotonLatency,"
             "ClickToPhotonLatency")

HEADER_V1 = ("Application,ProcessID,SwapChainAddress,Runtime,SyncInterval,PresentFlags,"
             "AllowsTearing,PresentMode,Dropped,TimeInSeconds,msInPresentAPI,"
             "msBetweenPresents,msUntilRenderComplete,msUntilDisplayed,"
             "msBetweenDisplayChange")


def row_v2(t, ft, pid=1234, app="game.exe", swap="0x1", mode="Hardware: Independent Flip",
           sync=0, cpu=5.0, gpu=9.0, displayed="16.7"):
    return (f"{app},{pid},{swap},DXGI,{sync},512,0,{mode},{t:.4f},{ft:.4f},{cpu},0.1,"
            f"0.5,{gpu},{gpu},0.02,12.0,{displayed},NA,{t:.4f},NA,NA,NA").encode()


def test_layout_v2_maps_all_columns():
    layout = _Layout(HEADER_V2)
    assert layout.ok
    for key in ("app", "pid", "swap", "t", "ft", "cpu_busy", "gpu_busy", "displayed"):
        assert layout.get(key) >= 0
    assert layout.get("t") == 8
    assert layout.get("ft") == 9


def test_layout_v1_falls_back_to_legacy_names():
    layout = _Layout(HEADER_V1)
    assert layout.ok
    assert layout.get("t") == 9          # TimeInSeconds
    assert layout.get("ft") == 11        # msBetweenPresents
    assert layout.get("cpu_busy") == -1  # nao existe no v1


def test_layout_rejects_garbage():
    assert not _Layout("foo,bar,baz").ok


def _feed(engine, rows):
    layout = _Layout(HEADER_V2)
    engine._ingest(layout, rows)


def test_ingest_and_aggregate():
    engine = FpsEngine(analysis_window=60.0)
    rows = [row_v2(i * 0.008, 8.0) for i in range(1, 400)]
    _feed(engine, rows)
    engine._recompute()

    streams = engine.snapshot()
    assert list(streams) == [1234]
    stream = streams[1234]
    assert stream.app == "game.exe"
    assert stream.present_mode == "Hardware: Independent Flip"
    assert stream.vsync is False
    assert round(stream.metrics.fps_avg) == 125
    assert stream.metrics.frames == 399


def test_ingest_rejects_invalid_frametimes():
    engine = FpsEngine()
    _feed(engine, [row_v2(1.0, 0.0), row_v2(1.1, 99999.0), row_v2(1.2, 8.0)])
    engine._recompute()
    assert engine.snapshot()[1234].metrics.frames == 1


def test_ingest_ignores_short_lines():
    engine = FpsEngine()
    _feed(engine, [b"lixo,1,2", b"", row_v2(1.0, 8.0)])
    engine._recompute()
    assert engine.snapshot()[1234].metrics.frames == 1


def test_vsync_flag_from_sync_interval():
    engine = FpsEngine()
    _feed(engine, [row_v2(i * 0.016, 16.7, sync=1) for i in range(1, 50)])
    engine._recompute()
    assert engine.snapshot()[1234].vsync is True


def test_best_swapchain_wins():
    engine = FpsEngine()
    rows = [row_v2(i * 0.008, 8.0, swap="0xA") for i in range(1, 300)]
    rows += [row_v2(i * 0.05, 50.0, swap="0xB") for i in range(1, 10)]
    _feed(engine, rows)
    engine._recompute()
    # a swapchain com mais frames na janela e a escolhida
    assert engine.snapshot()[1234].metrics.frames == 299


def test_two_processes_tracked_separately():
    engine = FpsEngine()
    rows = [row_v2(i * 0.008, 8.0, pid=1, app="a.exe") for i in range(1, 100)]
    rows += [row_v2(i * 0.02, 20.0, pid=2, app="b.exe") for i in range(1, 100)]
    _feed(engine, rows)
    engine._recompute()
    snap = engine.snapshot()
    assert {s.app for s in snap.values()} == {"a.exe", "b.exe"}
    assert round(snap[1].metrics.fps_avg) == 125
    assert round(snap[2].metrics.fps_avg) == 50


def test_apps_sorted_by_fps():
    engine = FpsEngine()
    rows = [row_v2(i * 0.02, 20.0, pid=2, app="lento.exe") for i in range(1, 60)]
    rows += [row_v2(i * 0.008, 8.0, pid=1, app="rapido.exe") for i in range(1, 60)]
    _feed(engine, rows)
    engine._recompute()
    assert engine.apps()[0][1] == "rapido.exe"


def test_frametimes_exposed_for_charts():
    engine = FpsEngine()
    _feed(engine, [row_v2(i * 0.008, 8.0) for i in range(1, 50)])
    engine._recompute()
    values = engine.frametimes(1234)
    assert len(values) == 49
    assert all(abs(v - 8.0) < 1e-6 for v in values)
    assert engine.frametimes(None) == []


def test_reset_clears_everything():
    engine = FpsEngine()
    _feed(engine, [row_v2(i * 0.008, 8.0) for i in range(1, 50)])
    engine._recompute()
    engine.reset()
    engine._recompute()
    assert engine.snapshot() == {}


def test_capture_collects_only_target_pid():
    engine = FpsEngine()
    engine.capture_start(1)
    _feed(engine, [row_v2(i * 0.008, 8.0, pid=1) for i in range(1, 30)]
          + [row_v2(i * 0.008, 8.0, pid=2) for i in range(1, 30)])
    captured = engine.capture_stop()
    assert len(captured) == 29
    assert all(abs(s[1] - 8.0) < 1e-6 for s in captured)


def test_na_columns_become_nan():
    engine = FpsEngine()
    _feed(engine, [row_v2(1.0, 8.0, displayed="NA")])
    samples = engine._raw[(1234, "0x1")]
    assert math.isnan(samples[0][6])


def test_analysis_window_limits_samples():
    engine = FpsEngine(analysis_window=1.0)
    _feed(engine, [row_v2(i * 0.01, 10.0) for i in range(1, 1000)])
    engine._recompute()
    assert engine.snapshot()[1234].metrics.frames <= 105


def test_expect_resets_watchdog_clock():
    engine = FpsEngine()
    engine.expect(99)
    first = engine._expected_since
    engine.expect(99)
    assert engine._expected_since == first
    engine.expect(100)
    assert engine._expected_pid == 100


def test_excluded_processes_are_declared():
    assert "dwm.exe" in fpsmod.EXCLUDED
    assert "explorer.exe" in fpsmod.EXCLUDED
