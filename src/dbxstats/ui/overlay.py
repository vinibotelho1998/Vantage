"""Overlay in-game estilo RTSS: click-through, topmost e compacto."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QFrame, QGridLayout, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from .. import theme
from ..platform import win
from . import fpspick

_MONO = "Cascadia Mono"
_FALLBACK_MONO = "Consolas"


def _mono(pt: float, weight: int = QFont.Weight.Normal) -> QFont:
    f = QFont(_MONO)
    f.setStyleHint(QFont.StyleHint.Monospace)
    f.setFamilies([_MONO, _FALLBACK_MONO])
    f.setPointSizeF(pt)
    f.setWeight(weight)
    return f


class GameOverlay(QWidget):
    def __init__(self, controller) -> None:
        super().__init__()
        self._ctl = controller
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool
            | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.WindowTransparentForInput)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self._build()

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self._root = QFrame()
        self._root.setObjectName("Overlay")
        self._root.setStyleSheet(
            "QFrame#Overlay { background: rgba(10, 13, 19, 210); border-radius: 10px;"
            " border: 1px solid rgba(255,255,255,20); }")
        outer.addWidget(self._root)

        lay = QVBoxLayout(self._root)
        lay.setContentsMargins(12, 9, 13, 10)
        lay.setSpacing(3)

        head = QHBoxLayout()
        head.setSpacing(8)
        brand = QLabel("DBX")
        brand.setFont(_mono(9, QFont.Weight.Bold))
        brand.setStyleSheet(f"color: {theme.accent_color(self._ctl.settings.accent)};")
        head.addWidget(brand)
        head.addStretch(1)
        self._fps = QLabel("—")
        self._fps.setFont(_mono(22, QFont.Weight.Bold))
        self._fps.setStyleSheet(f"color: {theme.MUTE};")
        unit = QLabel("FPS")
        unit.setFont(_mono(8, QFont.Weight.Bold))
        unit.setStyleSheet(f"color: {theme.FAINT};")
        unit.setAlignment(Qt.AlignmentFlag.AlignBottom)
        head.addWidget(self._fps)
        head.addWidget(unit)
        lay.addLayout(head)

        self._sub = QLabel("")
        self._sub.setFont(_mono(7.5))
        self._sub.setStyleSheet(f"color: {theme.FAINT};")
        lay.addWidget(self._sub)

        line = QFrame()
        line.setFixedHeight(1)
        line.setStyleSheet("background: rgba(255,255,255,22);")
        lay.addWidget(line)

        grid = QGridLayout()
        grid.setContentsMargins(0, 2, 0, 0)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(2)
        self._rows: dict[str, tuple[QLabel, QLabel]] = {}
        for r, (key, label) in enumerate(
                [("cpu", "CPU"), ("gpu", "GPU"), ("ram", "RAM"), ("ping", "PING")]):
            tag = QLabel(label)
            tag.setFont(_mono(8.5, QFont.Weight.Bold))
            tag.setStyleSheet(f"color: {theme.MUTE};")
            main = QLabel("—")
            main.setFont(_mono(10, QFont.Weight.DemiBold))
            main.setAlignment(Qt.AlignmentFlag.AlignRight)
            sub = QLabel("")
            sub.setFont(_mono(8.5))
            sub.setStyleSheet(f"color: {theme.FAINT};")
            grid.addWidget(tag, r, 0)
            grid.addWidget(main, r, 1)
            grid.addWidget(sub, r, 2)
            self._rows[key] = (main, sub)
        grid.setColumnStretch(2, 1)
        lay.addLayout(grid)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        hwnd = int(self.winId())
        win.set_clickthrough(hwnd, True)
        win.set_tool_window(hwnd)
        self.place()

    def place(self) -> None:
        self.adjustSize()
        screen = QApplication.primaryScreen()
        if screen is None:
            return
        area = screen.availableGeometry()
        m = 12
        w, h = self.width(), self.height()
        vert, _, horiz = self._ctl.settings.overlay_corner.partition("-")
        x = area.right() - w - m + 1 if horiz == "right" else area.left() + m
        y = area.bottom() - h - m + 1 if vert == "bottom" else area.top() + m
        self.move(int(x), int(y))

    def refresh(self) -> None:
        cfg = self._ctl.settings
        by_pid = self._ctl.fps.snapshot()
        chosen = fpspick.pick(by_pid, win.foreground_pid(), cfg.fps_pin)
        if chosen:
            inst, low, low01 = chosen[4], chosen[5], chosen[6]
            self._fps.setText(str(inst))
            self._fps.setStyleSheet(f"color: {theme.fps_color(inst)};")
            ft = 1000.0 / inst if inst > 0 else 0.0
            self._sub.setText(f"1% {low}   0.1% {low01}   {ft:.1f} ms")
        else:
            self._fps.setText("—")
            self._fps.setStyleSheet(f"color: {theme.MUTE};")
            self._sub.setText("sem jogo em foco")

        d = self._ctl.last_data() or {}
        self._set_row("cpu", _temp(d.get("cpu_temp")), theme.temp_color(d.get("cpu_temp")),
                      f"{d.get('cpu_pct', 0):.0f}%")
        g = d.get("gpu") or {}
        gw = g.get("watts")
        self._set_row("gpu", _temp(g.get("temp")), theme.temp_color(g.get("temp")),
                      f"{g.get('usage', 0)}%" + (f"  {gw:.0f}W" if gw else ""))
        self._set_row("ram", f"{d.get('ram_pct', 0):.0f}%", theme.TXT,
                      f"{d.get('ram_used', 0):.1f}G")
        ping = d.get("ping_ms")
        self._set_row("ping", f"{ping} ms" if ping is not None else "—",
                      theme.ping_color(ping), "")
        self.place()

    def _set_row(self, key: str, main: str, color: str, sub: str) -> None:
        m, s = self._rows[key]
        m.setText(main)
        m.setStyleSheet(f"color: {color};")
        s.setText(sub)


def _temp(t) -> str:
    return f"{t:.0f}°" if t is not None else "—"
