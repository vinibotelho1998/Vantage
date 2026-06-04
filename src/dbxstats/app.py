"""Controlador da aplicacao: engine, timers, janelas e ciclo de vida."""
from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from . import log
from .config import Settings
from .platform import autostart, win
from .sensors.collector import Collector
from .sensors.fps import FpsEngine
from .sensors.gpu import GpuReader
from .sensors.lhm import LhmReader
from .sensors.net import PingMonitor
from .stats import StatsTracker
from .ui import style
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
        self.panel.show()
        self._init_timers()
        autostart.set_enabled(self.settings.autostart)

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

    def _tick_fps(self) -> None:
        if self._panel_visible:
            self.panel.update_fps()
        if self._overlay is not None:
            self._overlay.refresh()

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
        self.panel.apply_settings(self.settings)
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

    def overlay_active(self) -> bool:
        return self._overlay is not None

    def toggle_overlay(self) -> None:
        if self._overlay is None:
            self._overlay = GameOverlay(self)
            self._overlay.show()
            _log.info("overlay ativado")
        else:
            self._overlay.close()
            self._overlay = None
            _log.info("overlay desativado")

    def toggle_panel(self) -> None:
        if self._panel_visible:
            self.panel.hide()
            self._panel_visible = False
        else:
            self.panel.show()
            self._panel_visible = True

    def clear_stats(self) -> None:
        self.stats.clear()

    def quit(self) -> None:
        self.collector.stop()
        self.ping.stop()
        self.fps.stop()
        if self._overlay is not None:
            self._overlay.close()
        self.tray.hide()
        self.lhm.close()
        self.qt.quit()
