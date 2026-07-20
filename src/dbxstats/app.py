"""Controlador da aplicacao: engine, timers, janelas e ciclo de vida."""
from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from . import log
from .config import Settings
from .platform import autostart, win
from .platform.hotkeys import MOD_ALT, MOD_CONTROL, HotkeyManager
from .sensors.collector import Collector
from .sensors.fps import FpsEngine
from .sensors.gpu import GpuReader
from .sensors.lhm import LhmReader
from .sensors.net import PingMonitor
from .stats import StatsTracker
from .ui import style
from .ui.benchmark import BenchmarkDialog, summarize
from .ui.main_panel import PanelWindow
from .ui.overlay import GameOverlay
from .ui.settings import SettingsDialog
from .ui.tray import Tray

_log = log.get("app")


class App:
    def __init__(self, qt: QApplication) -> None:
        self.qt = qt
        self.settings = Settings.load()
        self.stats = StatsTracker()
        self.lhm = LhmReader()
        self.gpu = GpuReader()
        self.ping = PingMonitor(self.settings.ping_host, self.settings.ping_port)
        self.fps = FpsEngine(self.settings.fps_window)
        self.collector = Collector(self.lhm, self.gpu, self.ping, self.settings.update_interval)

        self._last: dict = {}
        self._overlay: GameOverlay | None = None
        self._dialog: SettingsDialog | None = None
        self._panel_visible = True
        self._notified_tray = False
        self._bench_timer: QTimer | None = None
        self._bench_game = ""
        self._alerted: dict[str, float] = {}
        self._hotkeys: HotkeyManager | None = None

        self.qt.setQuitOnLastWindowClosed(False)
        self.qt.setStyleSheet(style.build_qss(self.settings.accent))
        self.panel = PanelWindow(self)
        self.tray = Tray(self)

    def boot(self) -> None:
        self.lhm.start()
        self.gpu.start_smi()
        self.ping.start()
        self.fps.start()
        self.collector.start()
        self._init_timers()
        self._apply_mode()
        self._hotkeys = HotkeyManager()
        self.qt.installNativeEventFilter(self._hotkeys)
        if not self._hotkeys.register(MOD_CONTROL | MOD_ALT, 0x52, self._hotkey_reset):
            _log.warning("nao foi possivel registrar Ctrl+Alt+R (em uso por outro app?)")
        autostart.set_enabled(self.settings.autostart)

    def _hotkey_reset(self) -> None:
        self.clear_stats()
        self.tray.notify("DBX Stats", "Estatísticas zeradas (Ctrl+Alt+R)")

    def run(self) -> int:
        self.boot()
        return self.qt.exec()

    def _init_timers(self) -> None:
        self._t_sys = QTimer(self.qt)
        self._t_sys.timeout.connect(self._tick_system)
        self._t_sys.start(int(self.settings.update_interval * 1000))
        self._t_fps = QTimer(self.qt)
        self._t_fps.timeout.connect(self._tick_fps)
        self._t_fps.start(120)
        self._t_clock = QTimer(self.qt)
        self._t_clock.timeout.connect(self.panel.update_clock)
        self._t_clock.start(1000)
        self._t_fs = QTimer(self.qt)
        self._t_fs.timeout.connect(self._tick_fullscreen)
        self._t_fs.start(1000)

    def last_data(self) -> dict:
        return self._last

    def _tick_system(self) -> None:
        self._last = self.collector.snapshot()
        if self._panel_visible:
            self.panel.update_system(self._last)
        self._check_alerts(self._last)

    def _check_alerts(self, d: dict) -> None:
        checks = [
            ("cpu", self.settings.alert_cpu_temp, d.get("cpu_temp"), "CPU"),
            ("gpu", self.settings.alert_gpu_temp, (d.get("gpu") or {}).get("temp"), "GPU"),
        ]
        for key, limit, val, label in checks:
            if not limit or val is None:
                continue
            if val >= limit and not self._alerted.get(key):
                self._alerted[key] = True
                self.tray.notify("DBX Stats — Alerta",
                                 f"{label} atingiu {val:.0f}°C (limite {limit}°C)")
            elif val <= limit - 3:
                self._alerted[key] = False

    def _tick_fps(self) -> None:
        busy = QApplication.activePopupWidget() is not None or self._dialog is not None
        if self._panel_visible:
            self.panel.update_fps()
            if self.settings.always_on_top and not busy:
                win.keep_topmost(int(self.panel.winId()))
        if self._overlay is not None:
            self._overlay.refresh()
            if not busy:
                win.keep_topmost(int(self._overlay.winId()))

    def _tick_fullscreen(self) -> None:
        if not self.settings.hide_fullscreen:
            if not self._panel_visible:
                self.panel.show()
                self._panel_visible = True
            return
        fs, hwnd = win.is_foreground_fullscreen()
        own = {int(self.panel.winId())}
        if self._overlay is not None:
            own.add(int(self._overlay.winId()))
        hide = fs and hwnd not in own
        if hide and self._panel_visible:
            self.panel.hide()
            self._panel_visible = False
        elif not hide and not self._panel_visible:
            self.panel.show()
            self._panel_visible = True

    # ── callbacks expostos as janelas ─────────────────────────────────────────-
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
        self.qt.setStyleSheet(style.build_qss(self.settings.accent))
        self.fps.set_window(self.settings.fps_window)
        self.collector.set_interval(self.settings.update_interval)
        self.ping.configure(self.settings.ping_host, self.settings.ping_port)
        self._t_sys.setInterval(int(self.settings.update_interval * 1000))
        self.tray.update_icon(self.settings.accent)
        self._apply_mode()
        if self._overlay is not None:
            self._overlay.place()
        autostart.set_enabled(self.settings.autostart)
        self.settings.save()

    def set_always_on_top(self, value: bool) -> None:
        self.settings.always_on_top = value
        self.panel.apply_settings(self.settings)
        self.settings.save()

    def set_locked(self, value: bool) -> None:
        self.settings.locked = value
        self.settings.save()

    def _apply_mode(self) -> None:
        mode = self.settings.mode
        self.settings.tablet_mode = mode == "tablet"
        if mode == "overlay":
            if self._overlay is None:
                self._overlay = GameOverlay(self)
                self._overlay.show()
            if self._panel_visible:
                self.panel.hide()
                self._panel_visible = False
        else:
            if self._overlay is not None:
                self._overlay.close()
                self._overlay = None
            self.panel.rebuild()
            if not self._panel_visible:
                self._panel_visible = True
            self.panel.show()

    def set_mode(self, mode: str) -> None:
        self.settings.mode = mode
        self._apply_mode()
        self.settings.save()

    def set_tablet_scale(self, scale: float) -> None:
        self.settings.tablet_scale = scale
        self.panel.rebuild()
        self.settings.save()

    def toggle_panel(self) -> None:
        if self._panel_visible:
            self.panel.hide()
            self._panel_visible = False
            if not self._notified_tray:
                self._notified_tray = True
                self.tray.notify("DBX Stats",
                                 "Continua na bandeja. Clique no icone para reabrir.")
        else:
            self.panel.show()
            self._panel_visible = True

    def start_benchmark(self, seconds: int = 30) -> None:
        if self._bench_timer is not None:
            return
        pid = self.panel.current_fps_pid()
        if pid is None:
            self.tray.notify("DBX Stats", "Nenhum jogo detectado para o benchmark.")
            return
        self._bench_game = self.fps.snapshot().get(pid, (0, "jogo"))[1]
        self.fps.benchmark_start(pid)
        self.tray.notify("DBX Stats", f"Benchmark iniciado — {seconds}s de {self._bench_game}")
        self._bench_timer = QTimer(self.qt)
        self._bench_timer.setSingleShot(True)
        self._bench_timer.timeout.connect(self._finish_benchmark)
        self._bench_timer.start(seconds * 1000)

    def _finish_benchmark(self) -> None:
        self._bench_timer = None
        summary = summarize(self.fps.benchmark_stop())
        if summary is None:
            self.tray.notify("DBX Stats", "Benchmark sem dados suficientes.")
            return
        BenchmarkDialog(summary, self._bench_game or "jogo").exec()

    def clear_stats(self) -> None:
        self.stats.clear()
        self.fps.reset()

    def quit(self) -> None:
        if self._hotkeys is not None:
            self._hotkeys.unregister_all()
        self.collector.stop()
        self.ping.stop()
        self.fps.stop()
        if self._overlay is not None:
            self._overlay.close()
        self.tray.hide()
        self.lhm.close()
        self.qt.quit()
