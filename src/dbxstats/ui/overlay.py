"""Overlay in-game estilo RTSS: click-through, sempre no topo e configuravel."""
from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from .. import theme
from ..core import units
from ..platform import win

_MONO = "Cascadia Mono"
_FALLBACK = "Consolas"


def _mono(pt: float, weight: int = QFont.Weight.Normal, scale: float = 1.0) -> QFont:
    f = QFont(_MONO)
    f.setStyleHint(QFont.StyleHint.Monospace)
    f.setFamilies([_MONO, _FALLBACK])
    f.setPointSizeF(pt * scale)
    f.setWeight(weight)
    return f


class GameOverlay(QWidget):
    """Painel minimo desenhado por cima do jogo."""

    def __init__(self, controller) -> None:
        super().__init__()
        self._ctl = controller
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowTransparentForInput)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self._rows: dict[str, tuple[QLabel, QLabel, QLabel]] = {}
        self._build()

    # ── construcao ───────────────────────────────────────────────────────────
    def _build(self) -> None:
        cfg = self._ctl.settings
        scale = cfg.overlay_scale
        alpha = int(cfg.overlay_opacity * 235)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self._root = QFrame()
        self._root.setObjectName("Overlay")
        self._root.setStyleSheet(
            f"QFrame#Overlay {{ background: rgba(6, 9, 14, {alpha});"
            f" border-radius: {int(10 * scale)}px;"
            f" border: 1px solid rgba(255,255,255,26); }}")
        outer.addWidget(self._root)

        lay = QVBoxLayout(self._root)
        m = int(11 * scale)
        lay.setContentsMargins(m, int(8 * scale), m + 1, int(9 * scale))
        lay.setSpacing(int(3 * scale))

        metrics = cfg.overlay_metrics
        if "fps" in metrics:
            head = QHBoxLayout()
            head.setSpacing(int(7 * scale))
            brand = QLabel("DBX")
            brand.setFont(_mono(8.5, QFont.Weight.Bold, scale))
            brand.setStyleSheet(f"color: {theme.accent_color(cfg.accent)};")
            head.addWidget(brand)
            head.addStretch(1)
            self._fps = QLabel("—")
            self._fps.setFont(_mono(23, QFont.Weight.Bold, scale))
            self._fps.setStyleSheet(f"color: {theme.MUTE};")
            unit = QLabel("FPS")
            unit.setFont(_mono(7.5, QFont.Weight.Bold, scale))
            unit.setStyleSheet(f"color: {theme.FAINT};")
            unit.setAlignment(Qt.AlignmentFlag.AlignBottom)
            head.addWidget(self._fps)
            head.addWidget(unit)
            lay.addLayout(head)
        else:
            self._fps = QLabel()

        self._sub = QLabel("")
        self._sub.setFont(_mono(7.5, QFont.Weight.Normal, scale))
        self._sub.setStyleSheet(f"color: {theme.FAINT};")
        lay.addWidget(self._sub)

        line = QFrame()
        line.setFixedHeight(1)
        line.setStyleSheet("background: rgba(255,255,255,24);")
        lay.addWidget(line)

        grid = QGridLayout()
        grid.setContentsMargins(0, int(2 * scale), 0, 0)
        grid.setHorizontalSpacing(int(8 * scale))
        grid.setVerticalSpacing(int(2 * scale))
        wanted = [(k, lbl) for k, lbl in (("cpu", "CPU"), ("gpu", "GPU"), ("ram", "RAM"),
                                          ("vram", "VRAM"), ("watts", "PWR"),
                                          ("ping", "PING"), ("clock", "HORA"))
                  if k in metrics]
        for r, (key, text) in enumerate(wanted):
            tag = QLabel(text)
            tag.setFont(_mono(8, QFont.Weight.Bold, scale))
            tag.setStyleSheet(f"color: {theme.MUTE};")
            main = QLabel("—")
            main.setFont(_mono(9.5, QFont.Weight.DemiBold, scale))
            main.setAlignment(Qt.AlignmentFlag.AlignRight)
            sub = QLabel("")
            sub.setFont(_mono(8, QFont.Weight.Normal, scale))
            sub.setStyleSheet(f"color: {theme.FAINT};")
            grid.addWidget(tag, r, 0)
            grid.addWidget(main, r, 1)
            grid.addWidget(sub, r, 2)
            self._rows[key] = (tag, main, sub)
        grid.setColumnStretch(2, 1)
        lay.addLayout(grid)

    def rebuild(self) -> None:
        old = self.layout()
        if old is not None:
            QWidget().setLayout(old)
        self._rows.clear()
        self._build()
        self.place()

    # ── posicionamento ───────────────────────────────────────────────────────
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
        area = screen.geometry()
        m = theme.scaled(14)
        w, h = self.width(), self.height()
        vert, _, horiz = self._ctl.settings.overlay_corner.partition("-")
        x = area.right() - w - m + 1 if horiz == "right" else area.left() + m
        y = area.bottom() - h - m + 1 if vert == "bottom" else area.top() + m
        self.move(int(x), int(y))

    # ── atualizacao ──────────────────────────────────────────────────────────
    def refresh(self) -> None:
        cfg = self._ctl.settings
        metrics = cfg.overlay_metrics
        stream = self._ctl.active_stream()

        if stream is not None:
            m = stream.metrics
            now = m.fps_now or m.fps_avg
            self._fps.setText(units.integer(now))
            self._fps.setStyleSheet(f"color: {theme.fps_color(now)};")
            parts = []
            if "low1" in metrics:
                parts.append(f"1% {units.integer(m.low_1)}")
            if "low01" in metrics:
                parts.append(f".1% {units.integer(m.low_01)}")
            if "frametime" in metrics:
                parts.append(f"{units.ms(m.ft_avg, 1)}")
            self._sub.setText("   ".join(parts))
        else:
            self._fps.setText("—")
            self._fps.setStyleSheet(f"color: {theme.MUTE};")
            self._sub.setText("sem jogo em foco")

        d = self._ctl.last_data() or {}
        g = d.get("gpu") or {}
        if "cpu" in self._rows:
            temp = d.get("cpu_temp")
            self._set("cpu", units.temp(temp), theme.temp_color(temp),
                      f"{d.get('cpu_pct', 0):.0f}%")
        if "gpu" in self._rows:
            temp = g.get("temp")
            self._set("gpu", units.temp(temp), theme.temp_color(temp),
                      f"{g.get('usage', 0):.0f}%")
        if "ram" in self._rows:
            self._set("ram", f"{d.get('ram_pct', 0):.0f}%",
                      theme.load_color(d.get("ram_pct")),
                      f"{d.get('ram_used', 0):.1f}G")
        if "vram" in self._rows:
            self._set("vram", units.percent(g.get("vram_pct")),
                      theme.load_color(g.get("vram_pct")),
                      f"{g.get('vram_used', 0) / 1024:.1f}G")
        if "watts" in self._rows:
            total = (d.get("cpu_watts") or 0) + (g.get("watts") or 0)
            self._set("watts", f"{total:.0f}W", theme.TXT,
                      f"G {units.watts(g.get('watts'), 0)}")
        if "ping" in self._rows:
            ping = d.get("ping_ms")
            self._set("ping", units.ms(ping, 0), theme.ping_color(ping), "")
        if "clock" in self._rows:
            self._set("clock", datetime.now().strftime("%H:%M"), theme.TXT, "")
        self.place()

    def _set(self, key: str, main: str, color: str, sub: str) -> None:
        row = self._rows.get(key)
        if row is None:
            return
        _tag, value, subtitle = row
        value.setText(main)
        value.setStyleSheet(f"color: {color};")
        subtitle.setText(sub)
