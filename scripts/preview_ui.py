"""Renderiza overlay in-game e dialogo de configuracoes offscreen para PNG."""
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
from dbxstats.ui.overlay import GameOverlay
from dbxstats.ui.settings import SettingsDialog

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SNAP = {
    "lhm_ok": True, "cpu_pct": 42.0, "cpu_temp": 64, "cpu_watts": 88.0,
    "ram_used": 19.1, "ram_total": 32, "ram_pct": 60,
    "gpu": {"name": "NVIDIA GeForce RTX 4060", "usage": 74, "temp": 67,
            "watts": 118.0, "watts_estimated": False},
    "ping_ms": 19,
}


class MockFps:
    def snapshot(self):
        return {4242: (146, "Cyberpunk2077.exe", 0.0, 141, 149, 101, 83)}

    def graph_buffer(self, pid):
        return [16.6 + 3 * math.sin(i / 6) for i in range(300)]


class MockController:
    def __init__(self):
        self.settings = Settings()
        self.stats = StatsTracker()
        self.fps = MockFps()

    def last_data(self):
        return SNAP

    def clear_stats(self): ...
    def on_settings_changed(self): ...


def _grab(widget, out: str, bg: str = "#202530") -> None:
    deadline = time.monotonic() + 0.5
    while time.monotonic() < deadline:
        QApplication.instance().processEvents()
        time.sleep(0.02)
    size = widget.size()
    img = QImage(size, QImage.Format.Format_ARGB32)
    img.fill(QColor(bg))
    painter = QPainter(img)
    widget.render(painter, QPoint(0, 0))
    painter.end()
    img.save(out)
    print(f"salvo: {out}  ({size.width()}x{size.height()})")


def main() -> int:
    app = QApplication(sys.argv)
    ctl = MockController()
    app.setStyleSheet(style.build_qss(ctl.settings.accent))

    overlay = GameOverlay(ctl)
    overlay.show()
    overlay.refresh()
    _grab(overlay, os.path.join(ROOT, "preview_overlay.png"), bg="#0e1726")

    dialog = SettingsDialog(ctl, 0)
    dialog.show()
    dialog.adjustSize()
    _grab(dialog, os.path.join(ROOT, "preview_settings.png"), bg="#05070a")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
