"""Controlador da aplicacao: sensores, timers, janelas e ciclo de vida.

A UI nunca fala com um sensor diretamente — tudo passa por aqui, o que mantem as
telas burras (e baratas) e concentra as regras num lugar so.
"""
from __future__ import annotations

import json
import time
from datetime import datetime

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from . import log, paths, theme
from .config import Settings
from .core import export
from .core import frames as fr
from .core.series import Accumulator, History
from .platform import autostart, win
from .platform.hotkeys import MOD_ALT, MOD_CONTROL, HotkeyManager
from .sensors.collector import Collector
from .sensors.fps import FpsEngine
from .sensors.gpu import GpuReader
from .sensors.lhm import LhmReader
from .sensors.net import PingMonitor
from .sensors.procs import ProcessMonitor
from .ui import style
from .ui.main_window import MainWindow
from .ui.overlay import GameOverlay
from .ui.settings import SettingsDialog
from .ui.tray import Tray

_log = log.get("app")

FAST_TICK_MS = 120
FOCUS_TICK_MS = 500
BENCH_HISTORY_MAX = 40

# metricas do snapshot que alimentam graficos e acumulador da sessao
_SERIES = (
    ("cpu_pct", lambda d, g: d.get("cpu_pct")),
    ("cpu_temp", lambda d, g: d.get("cpu_temp")),
    ("cpu_watts", lambda d, g: d.get("cpu_watts")),
    ("cpu_mhz", lambda d, g: d.get("cpu_mhz")),
    ("gpu_pct", lambda d, g: g.get("usage")),
    ("gpu_temp", lambda d, g: g.get("temp")),
    ("gpu_watts", lambda d, g: g.get("watts")),
    ("gpu_mhz", lambda d, g: g.get("freq")),
    ("gpu_mem_mhz", lambda d, g: g.get("mem_freq")),
    ("vram_pct", lambda d, g: g.get("vram_pct")),
    ("ram_pct", lambda d, g: d.get("ram_pct")),
    ("swap_pct", lambda d, g: d.get("swap_pct")),
    ("disk_r", lambda d, g: d.get("disk_r")),
    ("disk_w", lambda d, g: d.get("disk_w")),
    ("net_dl", lambda d, g: d.get("net_dl")),
    ("net_ul", lambda d, g: d.get("net_ul")),
    ("ping_ms", lambda d, g: d.get("ping_ms")),
    ("packet_loss", lambda d, g: d.get("packet_loss")),
)

_SYSTEM_KEYS = (("cpu", "cpu_pct"), ("cpu_temp", "cpu_temp"), ("cpu_watts", "cpu_watts"),
                ("gpu", "gpu_pct"), ("gpu_temp", "gpu_temp"), ("gpu_watts", "gpu_watts"),
                ("ram", "ram_pct"), ("vram", "vram_pct"))


class App:
    def __init__(self, qt: QApplication) -> None:
        self.qt = qt
        self.settings = Settings.load()
        theme.set_scale(self.settings.ui_scale)

        self.stats = Accumulator()
        self.history = History(self._history_depth())
        self.lhm = LhmReader()
        self.gpu = GpuReader()
        self.ping = PingMonitor(self.settings.ping_host, self.settings.ping_port)
        self.fps = FpsEngine(self.settings.fps_window, self.settings.fps_now_window)
        self.procs = ProcessMonitor()
        self.collector = Collector(self.lhm, self.gpu, self.ping,
                                   self.settings.update_interval)

        self._data: dict = {}
        self._stream = None
        self._fg_pid = 0
        self._fg_fullscreen = False
        self._overlay: GameOverlay | None = None
        self._dialog: SettingsDialog | None = None
        self._hotkeys: HotkeyManager | None = None
        self._t_sys: QTimer | None = None
        self._alerted: dict[str, bool] = {}
        self._tray_hinted = False

        self._bench_active = False
        self._bench_started = 0.0
        self._bench_total = 0.0
        self._bench_game = ""
        self._bench_pid: int | None = None
        self._bench_env = Accumulator()
        self._bench_result: dict | None = None
        self._bench_rev = 0
        self.bench_history: list[dict] = _load_bench_history()

        qt.setQuitOnLastWindowClosed(False)
        qt.setStyleSheet(style.build_qss(self.settings.accent))
        self.window = MainWindow(self)
        self.tray = Tray(self)

    # ── ciclo de vida ────────────────────────────────────────────────────────
    def run(self) -> int:
        self.boot()
        return self.qt.exec()

    def boot(self) -> None:
        self.lhm.start()
        self.gpu.start_smi()
        self.ping.start()
        self.fps.start()
        self.procs.start()
        self.collector.start()

        self.window.restore_geometry()
        if not self.settings.start_minimized:
            self.window.show()
        self._apply_overlay()
        self._init_timers()
        self._init_hotkeys()
        autostart.set_enabled(self.settings.autostart)

    def _init_timers(self) -> None:
        self._t_sys = QTimer(self.qt)
        self._t_sys.timeout.connect(self._tick_system)
        self._t_sys.start(int(self.settings.update_interval * 1000))

        self._t_fast = QTimer(self.qt)
        self._t_fast.timeout.connect(self._tick_fast)
        self._t_fast.start(FAST_TICK_MS)

        self._t_focus = QTimer(self.qt)
        self._t_focus.timeout.connect(self._tick_focus)
        self._t_focus.start(FOCUS_TICK_MS)

        self._t_clock = QTimer(self.qt)
        self._t_clock.timeout.connect(self.window.tick_clock)
        self._t_clock.start(1000)

    def _init_hotkeys(self) -> None:
        self._hotkeys = HotkeyManager()
        self.qt.installNativeEventFilter(self._hotkeys)
        mods = MOD_CONTROL | MOD_ALT
        bindings = ((0x52, self._hotkey_reset, "Ctrl+Alt+R"),
                    (0x4F, self.toggle_overlay, "Ctrl+Alt+O"),
                    (0x42, self._hotkey_benchmark, "Ctrl+Alt+B"))
        for vk, callback, name in bindings:
            if not self._hotkeys.register(mods, vk, callback):
                _log.warning("nao foi possivel registrar %s (em uso por outro app?)", name)

    def quit(self) -> None:
        self.window.store_geometry()
        self.settings.save()
        _save_bench_history(self.bench_history)
        if self._hotkeys is not None:
            self._hotkeys.unregister_all()
        self.collector.stop()
        self.procs.stop()
        self.ping.stop()
        self.gpu.stop()
        self.fps.stop()
        if self._overlay is not None:
            self._overlay.close()
        self.tray.hide()
        self.lhm.close()
        self.qt.quit()

    # ── timers ───────────────────────────────────────────────────────────────
    def _tick_system(self) -> None:
        data = self.collector.snapshot()
        if not data:
            return
        self._data = data
        gpu = data.get("gpu") or {}

        for key, getter in _SERIES:
            value = getter(data, gpu)
            self.history.push(key, value)
            self.stats.update(key, value)

        stream = self._stream
        if stream is not None:
            m = stream.metrics
            self.history.push("fps", m.fps_now)
            self.history.push("fps_low1", m.low_1)
            self.stats.update("fps", m.fps_now)
        else:
            self.history.push("fps", None)
            self.history.push("fps_low1", None)

        for node in self.lhm.tree():
            self.stats.update(node.key, node.value)

        if self._bench_active:
            for key, source in _SYSTEM_KEYS:
                self._bench_env.update(key, self.stats.last(source))

        if self.window.isVisible():
            self.window.tick_system(data)
        self._check_alerts(data, gpu)
        self._update_tray_tooltip(data, gpu)

    def _tick_fast(self) -> None:
        self._stream = self._select_stream()
        if self.window.isVisible():
            self.window.tick_fps()
        if self._overlay is not None:
            self._overlay.refresh()
            win.keep_topmost(int(self._overlay.winId()))
        if self._bench_active and time.monotonic() - self._bench_started >= self._bench_total:
            self.benchmark_stop()

    def _tick_focus(self) -> None:
        fullscreen, hwnd = win.is_foreground_fullscreen()
        own = {int(self.window.winId())}
        if self._overlay is not None:
            own.add(int(self._overlay.winId()))
        self._fg_fullscreen = fullscreen and hwnd not in own
        self._fg_pid = win.window_pid(hwnd) if hwnd not in own else 0
        self.fps.expect(self._fg_pid if self._fg_fullscreen else None)
        self.procs.set_game_pids(self.fps.snapshot().keys())
        if self.settings.overlay_enabled and self.settings.overlay_auto_game:
            self._sync_overlay_visibility()

    # ── selecao do jogo ──────────────────────────────────────────────────────
    def _select_stream(self):
        streams = self.fps.snapshot()
        if not streams:
            return None
        pin = self.settings.fps_pin
        if pin:
            matches = [s for s in streams.values() if s.app.lower() == pin.lower()]
            return max(matches, key=lambda s: s.metrics.frames) if matches else None
        if self.settings.fps_only_fullscreen:
            if not self._fg_fullscreen:
                return None
            return streams.get(self._fg_pid)
        if self._fg_pid in streams:
            return streams[self._fg_pid]
        return max(streams.values(), key=lambda s: s.metrics.frames)

    def active_stream(self):
        return self._stream

    def last_data(self) -> dict:
        return self._data

    def fps_hint(self) -> str:
        if not self.fps.running:
            return self.fps.status
        if self.settings.fps_pin:
            return f"aguardando {self.settings.fps_pin}"
        if self.settings.fps_only_fullscreen and not self._fg_fullscreen:
            return "nenhum jogo em tela cheia"
        return "nenhum jogo apresentando quadros"

    # ── alertas ──────────────────────────────────────────────────────────────
    def _check_alerts(self, d: dict, gpu: dict) -> None:
        if not self.settings.alerts_enabled:
            return
        checks = (
            ("cpu_temp", self.settings.alert_cpu_temp, d.get("cpu_temp"),
             "Temperatura da CPU", "°C"),
            ("gpu_temp", self.settings.alert_gpu_temp, gpu.get("temp"),
             "Temperatura da GPU", "°C"),
            ("ram", self.settings.alert_ram_pct, d.get("ram_pct"), "Uso de RAM", "%"),
            ("vram", self.settings.alert_vram_pct, gpu.get("vram_pct"), "Uso de VRAM", "%"),
        )
        for key, limit, value, name, unit in checks:
            if not limit or value is None:
                continue
            if value >= limit and not self._alerted.get(key):
                self._alerted[key] = True
                self.notify("DBX Stats — alerta",
                            f"{name}: {value:.0f}{unit} (limite {limit}{unit})")
            elif value <= limit - 4:
                self._alerted[key] = False

    def _update_tray_tooltip(self, d: dict, gpu: dict) -> None:
        parts = [f"CPU {d.get('cpu_pct', 0):.0f}%"]
        if d.get("cpu_temp"):
            parts.append(f"{d['cpu_temp']:.0f}°C")
        parts.append(f"GPU {gpu.get('usage', 0):.0f}%")
        if gpu.get("temp"):
            parts.append(f"{gpu['temp']:.0f}°C")
        if self._stream is not None:
            fps = self._stream.metrics.fps_now
            if fps:
                parts.append(f"{fps:.0f} fps")
        self.tray.set_tooltip("DBX Stats — " + "  ·  ".join(parts))

    # ── acoes expostas a UI ──────────────────────────────────────────────────
    def notify(self, title: str, message: str) -> None:
        self.tray.notify(title, message)

    def notify_tray_hint(self) -> None:
        if not self._tray_hinted:
            self._tray_hinted = True
            self.notify("DBX Stats", "Continua rodando na bandeja. Clique no ícone "
                                     "para reabrir.")

    def toggle_window(self) -> None:
        if self.window.isVisible():
            self.window.store_geometry()
            self.window.hide()
        else:
            self.window.show()
            self.window.raise_()
            self.window.activateWindow()

    def show_view(self, key: str) -> None:
        if not self.window.isVisible():
            self.window.show()
        self.window.show_view(key)
        self.window.raise_()
        self.window.activateWindow()

    def save_settings(self) -> None:
        self.settings.save()

    def open_settings(self, tab: int = 0) -> None:
        if self._dialog is not None:
            self._dialog.raise_()
            self._dialog.activateWindow()
            return
        self._dialog = SettingsDialog(self, tab)
        self._dialog.finished.connect(lambda _r: setattr(self, "_dialog", None))
        self._dialog.show()

    def on_settings_changed(self) -> None:
        cfg = self.settings
        self.qt.setStyleSheet(style.build_qss(cfg.accent))
        self.collector.set_interval(cfg.update_interval)
        self.ping.configure(cfg.ping_host, cfg.ping_port)
        self.fps.set_windows(cfg.fps_window, cfg.fps_now_window)
        self.history.resize(self._history_depth())
        if self._t_sys is not None:
            self._t_sys.setInterval(int(cfg.update_interval * 1000))
        self.window.apply_settings()
        self._apply_overlay()
        self.tray.sync()
        autostart.set_enabled(cfg.autostart)
        cfg.save()

    def set_fps_pin(self, name: str) -> None:
        self.settings.fps_pin = name
        self.settings.save()
        self.window.apply_settings()

    def set_fps_window(self, seconds: float) -> None:
        self.settings.fps_window = seconds
        self.settings.sanitize()
        self.fps.set_windows(self.settings.fps_window, self.settings.fps_now_window)
        self.settings.save()
        self.window.apply_settings()

    def restart_capture(self) -> None:
        self.fps.restart()
        self.notify("DBX Stats", "Captura de FPS reiniciada.")

    def clear_stats(self) -> None:
        self.stats.clear()
        self.history.clear()
        self.fps.reset()

    def _hotkey_reset(self) -> None:
        self.clear_stats()
        self.notify("DBX Stats", "Estatísticas zeradas (Ctrl+Alt+R)")

    def _hotkey_benchmark(self) -> None:
        if self._bench_active:
            self.benchmark_stop()
        else:
            self.benchmark_start(self.settings.bench_seconds)

    def _history_depth(self) -> int:
        return max(80, int(self.settings.history_window / self.settings.update_interval) + 4)

    # ── overlay ──────────────────────────────────────────────────────────────
    def toggle_overlay(self) -> None:
        self.settings.overlay_enabled = not self.settings.overlay_enabled
        self.settings.save()
        self._apply_overlay()
        self.tray.sync()

    def _apply_overlay(self) -> None:
        if not self.settings.overlay_enabled:
            if self._overlay is not None:
                self._overlay.close()
                self._overlay = None
            return
        if self._overlay is None:
            self._overlay = GameOverlay(self)
        else:
            self._overlay.rebuild()
        self._sync_overlay_visibility()

    def _sync_overlay_visibility(self) -> None:
        if self._overlay is None:
            return
        show = True
        if self.settings.overlay_auto_game:
            show = self._stream is not None or self._fg_fullscreen
        if show and not self._overlay.isVisible():
            self._overlay.show()
        elif not show and self._overlay.isVisible():
            self._overlay.hide()

    # ── benchmark ────────────────────────────────────────────────────────────
    def benchmark_active(self) -> bool:
        return self._bench_active

    def benchmark_state(self) -> dict:
        return {
            "active": self._bench_active,
            "elapsed": (time.monotonic() - self._bench_started) if self._bench_active else 0.0,
            "total": self._bench_total,
            "frames": self.fps.capture_peek() if self._bench_active else 0,
            "game": self._bench_game,
        }

    def benchmark_last(self) -> dict | None:
        return self._bench_result

    def benchmark_start(self, seconds: int) -> None:
        if self._bench_active:
            return
        stream = self._stream
        if stream is None:
            self.notify("DBX Stats", "Nenhum jogo detectado para o benchmark.")
            return
        self._bench_active = True
        self._bench_pid = stream.pid
        self._bench_game = stream.app or "jogo"
        self._bench_started = time.monotonic()
        self._bench_total = float(seconds)
        self._bench_env = Accumulator()
        self.fps.capture_start(stream.pid)
        self.notify("DBX Stats", f"Benchmark iniciado — {seconds}s de {self._bench_game}")

    def benchmark_stop(self) -> None:
        if not self._bench_active:
            return
        self._bench_active = False
        samples = self.fps.capture_stop()
        if len(samples) < 20:
            self.notify("DBX Stats", "Benchmark sem amostras suficientes.")
            return
        metrics = fr.compute(samples, self.settings.fps_now_window)
        system = {}
        for key, _source in _SYSTEM_KEYS:
            agg = self._bench_env.get(key)
            if agg:
                system[key] = (agg[1], agg[2])
        self._bench_rev += 1
        self._bench_result = {
            "_rev": self._bench_rev,
            "game": self._bench_game,
            "metrics": metrics,
            "frametimes": [s[fr.FT] for s in samples],
            "samples": samples,
            "system": system,
        }
        self.bench_history.append({
            "time": datetime.now().strftime("%d/%m %H:%M"),
            "game": self._bench_game,
            "avg": metrics.fps_avg or 0.0,
            "low1": metrics.low_1 or 0.0,
            "low01": metrics.low_01 or 0.0,
            "smooth": metrics.smoothness or 0.0,
        })
        del self.bench_history[:-BENCH_HISTORY_MAX]
        _save_bench_history(self.bench_history)
        if self.settings.bench_autosave:
            export.export_benchmark(_summary_row(metrics), self._bench_game)
        self.notify("DBX Stats",
                    f"Benchmark concluído — {metrics.fps_avg:.0f} fps médio, "
                    f"1% low {metrics.low_1:.0f}")
        self.show_view("benchmark")

    def benchmark_export(self):
        if not self._bench_result:
            return None
        return export.export_frames(self._bench_result["samples"],
                                    self._bench_result["game"])


def _summary_row(m: fr.FrameMetrics) -> dict:
    return {k: v for k, v in m.as_dict().items() if isinstance(v, (int, float))}


def _bench_file():
    return paths.data_dir() / "benchmarks.json"


def _load_bench_history() -> list[dict]:
    try:
        return json.loads(_bench_file().read_text(encoding="utf-8"))[-BENCH_HISTORY_MAX:]
    except Exception:
        return []


def _save_bench_history(history: list[dict]) -> None:
    try:
        _bench_file().write_text(json.dumps(history, ensure_ascii=False),
                                 encoding="utf-8")
    except OSError:
        pass
