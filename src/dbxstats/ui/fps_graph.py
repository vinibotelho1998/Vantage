"""Grafico duplo de FPS (cima) e frametime (baixo) a partir do buffer do motor."""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from .. import theme


class FpsGraph(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._buf: list[float] = []
        self.setFixedHeight(theme.scaled(54))
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_buffer(self, buf) -> None:
        self._buf = list(buf)
        self.update()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(theme.BG_ALT))
        p.drawRoundedRect(QRectF(0, 0, w, h), 8, 8)

        raw = self._buf
        if len(raw) < 2:
            p.setPen(QColor(theme.FAINT))
            p.setFont(QFont(theme.FONT_UI, 8))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "aguardando frametime")
            return

        ft = _resample(raw, int(w))
        fps = [1000.0 / ms if ms > 0 else 0.0 for ms in ft]
        n = len(ft)
        pad = 4.0
        h_fps = int(h * 0.54)
        h_ft = h - h_fps - 1
        max_fps = max(_p95(fps) * 1.15, 65.0)
        max_ft = max(_p95(ft) * 1.15, 1000.0 / 30)

        def xp(i: int) -> float:
            return i * (w - 1) / max(n - 1, 1)

        top_path = QPainterPath()
        for i, v in enumerate(fps):
            y = (h_fps - 2) - min(v, max_fps) / max_fps * (h_fps - 2 * pad)
            (top_path.moveTo if i == 0 else top_path.lineTo)(xp(i), y)
        _fill_under(p, top_path, w, h_fps, theme.OK)
        p.setPen(QPen(QColor(theme.OK), 1.5))
        p.drawPath(top_path)

        y60 = (h_fps - 2) - 60.0 / max_fps * (h_fps - 2 * pad)
        if 0 < y60 < h_fps:
            p.setPen(QPen(QColor(theme.LINE_HI), 1, Qt.PenStyle.DashLine))
            p.drawLine(0, int(y60), int(w), int(y60))
        p.setPen(QColor(theme.OK))
        p.setFont(QFont(theme.FONT_UI, 7, QFont.Weight.Bold))
        p.drawText(6, 13, "FPS")

        p.setPen(QPen(QColor(theme.LINE), 1))
        p.drawLine(0, h_fps, int(w), h_fps)

        bot_path = QPainterPath()
        for i, ms in enumerate(ft):
            y = h_fps + 1 + min(ms, max_ft) / max_ft * (h_ft - 2 * pad)
            (bot_path.moveTo if i == 0 else bot_path.lineTo)(xp(i), y)
        _fill_to(p, bot_path, w, h, theme.DISK)
        p.setPen(QPen(QColor(theme.DISK), 1.5))
        p.drawPath(bot_path)

        y_ref = h_fps + 1 + (1000.0 / 60) / max_ft * (h_ft - 2 * pad)
        if h_fps < y_ref < h:
            p.setPen(QPen(QColor(theme.LINE_HI), 1, Qt.PenStyle.DashLine))
            p.drawLine(0, int(y_ref), int(w), int(y_ref))
        p.setPen(QColor(theme.DISK))
        p.drawText(6, h_fps + 13, "FT")


def _resample(raw: list[float], width: int) -> list[float]:
    n = len(raw)
    if n <= width or width <= 0:
        return list(raw)
    step = n / width
    out = []
    for i in range(width):
        s = int(i * step)
        e = max(s + 1, int((i + 1) * step))
        chunk = raw[s:e]
        out.append(sum(chunk) / len(chunk))
    return out


def _p95(seq: list[float]) -> float:
    s = sorted(seq)
    return s[min(len(s) - 1, int(len(s) * 0.95))]


def _fill_under(p: QPainter, path: QPainterPath, w: float, base: float, color: str) -> None:
    fill = QPainterPath(path)
    fill.lineTo(w, base)
    fill.lineTo(0, base)
    fill.closeSubpath()
    grad = QLinearGradient(0, 0, 0, base)
    top = QColor(color)
    top.setAlpha(70)
    bottom = QColor(color)
    bottom.setAlpha(0)
    grad.setColorAt(0.0, top)
    grad.setColorAt(1.0, bottom)
    p.fillPath(fill, grad)


def _fill_to(p: QPainter, path: QPainterPath, w: float, h: float, color: str) -> None:
    fill = QPainterPath(path)
    fill.lineTo(w, h)
    fill.lineTo(0, h)
    fill.closeSubpath()
    grad = QLinearGradient(0, 0, 0, h)
    c = QColor(color)
    c.setAlpha(55)
    c2 = QColor(color)
    c2.setAlpha(0)
    grad.setColorAt(0.0, c)
    grad.setColorAt(1.0, c2)
    p.fillPath(fill, grad)
