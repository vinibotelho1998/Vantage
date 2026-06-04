"""Renderiza o painel principal offscreen para PNG, com dados mockados."""
from __future__ import annotations

import math
import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication

from dbxstats.config import Settings
from dbxstats.stats import StatsTracker
from dbxstats.ui import style
from dbxstats.ui.main_panel import PanelWindow

OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "preview_panel.png")

SNAP = {
    "lhm_ok": True, "cpu_pct": 37.5, "cpu_mhz": 4250, "cpu_temp": 61,
    "cpu_watts": 78.5, "cpu_fan": 1180, "uptime": "03:42:15",
    "ram_used": 18.4, "ram_total": 32, "ram_avail": 13.6, "ram_pct": 57, "ram_freq": 3200,
    "disk_used": 318, "disk_total": 442, "disk_pct": 72,
    "disk_r": 1.5e6, "disk_w": 3.2e5, "nvme_temp": 44,
    "net_dl": 2.4e6, "net_ul": 3.1e5, "ping_ms": 22, "packet_loss": 0,
    "gpu": {"name": "NVIDIA GeForce RTX 4060", "usage": 68, "temp": 63,
            "fan_rpm": 1500, "fan_pct": 45, "watts": 102.5, "watts_estimated": False,
            "freq": 2580, "mem_freq": 8500, "vram_used": 5400, "vram_total": 8188},
}


class MockFps:
    def snapshot(self):
        return {1234: (142, "Cyberpunk2077.exe", 0.0, 138, 145, 96, 78)}

    def graph_buffer(self, pid):
        return [16.6 + 3 * math.sin(i / 6) + (10 if i % 41 == 0 else 0) for i in range(400)]


class MockController:
    def __init__(self, show_stats: bool):
        self.settings = Settings()
        self.settings.show_stats = show_stats
        self.stats = StatsTracker()
        self.fps = MockFps()

    def save_settings(self): ...
    def open_settings(self, tab=0): ...
    def set_always_on_top(self, v): ...
    def set_locked(self, v): ...
    def overlay_active(self): return False
    def toggle_overlay(self): ...
    def clear_stats(self): ...
    def quit(self): ...


def render(show_stats: bool, out: str) -> None:
    ctl = MockController(show_stats)
    panel = PanelWindow(ctl)
    panel.setStyleSheet(style.build_qss(ctl.settings.accent))
    panel.show()
    for _ in range(5):
        ctl.stats.update("cpu_pct", 30 + _ * 3)
        ctl.stats.update("cpu_temp", 55 + _ * 2)
        panel.update_system(SNAP)
        panel.update_fps()
        panel.update_clock()
    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline:
        QApplication.instance().processEvents()
        time.sleep(0.02)

    size = panel.size()
    img = QImage(size, QImage.Format.Format_ARGB32)
    img.fill(QColor("#202530"))
    painter = QPainter(img)
    panel.render(painter, QPoint(0, 0))
    painter.end()
    img.save(out)
    print(f"salvo: {out}  ({size.width()}x{size.height()})")


def main() -> int:
    QApplication(sys.argv)
    render(False, OUT)
    render(True, OUT.replace(".png", "_stats.png"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
