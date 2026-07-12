"""Widgets customizados: barra animada, sparkline, linhas de metrica e cards."""
from __future__ import annotations

from collections import deque

from PySide6.QtCore import Property, QEasingCurve, QPropertyAnimation, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from .. import theme


def make_font(pt: float, weight: int = QFont.Normal, family: str = theme.FONT_UI) -> QFont:
    f = QFont(family)
    f.setPointSizeF(pt * theme.SCALE)
    f.setWeight(weight)
    return f


def divider() -> QFrame:
    f = QFrame()
    f.setObjectName("Divider")
    f.setFixedHeight(max(1, theme.scaled(1)))
    return f


class ProgressBar(QWidget):
    def __init__(self, color: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._value = 0.0
        self._color = QColor(color)
        self.setFixedHeight(theme.scaled(6))
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._anim = QPropertyAnimation(self, b"value", self)
        self._anim.setDuration(400)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)

    def _get_value(self) -> float:
        return self._value

    def _set_value(self, v: float) -> None:
        self._value = max(0.0, min(100.0, float(v)))
        self.update()

    value = Property(float, _get_value, _set_value)

    def animate_to(self, v: float) -> None:
        v = max(0.0, min(100.0, float(v)))
        if abs(v - self._value) < 0.5:
            self._set_value(v)
            return
        self._anim.stop()
        self._anim.setStartValue(self._value)
        self._anim.setEndValue(v)
        self._anim.start()

    def set_color(self, color: str) -> None:
        c = QColor(color)
        if c != self._color:
            self._color = c
            self.update()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        r = h / 2.0
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(theme.LINE))
        p.drawRoundedRect(QRectF(0, 0, w, h), r, r)
        fw = w * self._value / 100.0
        if fw >= 1:
            grad = QLinearGradient(0, 0, w, 0)
            grad.setColorAt(0.0, self._color)
            grad.setColorAt(1.0, self._color.lighter(125))
            p.setBrush(grad)
            p.drawRoundedRect(QRectF(0, 0, max(fw, 2 * r), h), r, r)


class Sparkline(QWidget):
    def __init__(self, color: str, parent: QWidget | None = None,
                 maxlen: int = 80, fixed_max: float | None = None, height: int = 18) -> None:
        super().__init__(parent)
        self._color = QColor(color)
        self._data: deque[float] = deque(maxlen=maxlen)
        self._fixed_max = fixed_max
        self.setFixedHeight(theme.scaled(height))
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def push(self, v) -> None:
        try:
            self._data.append(float(v))
        except (TypeError, ValueError):
            return
        self.update()

    def set_color(self, color: str) -> None:
        self._color = QColor(color)
        self.update()

    def paintEvent(self, _event) -> None:
        n = len(self._data)
        if n < 2:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        vals = list(self._data)
        if self._fixed_max is not None:
            lo, hi = 0.0, float(self._fixed_max)
        else:
            lo, hi = min(vals), max(vals)
        rng = max(hi - lo, 1e-6)
        pad = 3.0

        def y_of(v: float) -> float:
            y = (h - pad) - ((v - lo) / rng) * (h - 2 * pad)
            return max(pad, min(h - pad, y))

        path = QPainterPath()
        path.moveTo(0.0, y_of(vals[0]))
        for i in range(1, n):
            path.lineTo(w * i / (n - 1), y_of(vals[i]))

        fill = QPainterPath(path)
        fill.lineTo(w, h)
        fill.lineTo(0, h)
        fill.closeSubpath()
        grad = QLinearGradient(0, 0, 0, h)
        top = QColor(self._color)
        top.setAlpha(80)
        bottom = QColor(self._color)
        bottom.setAlpha(0)
        grad.setColorAt(0.0, top)
        grad.setColorAt(1.0, bottom)
        p.fillPath(fill, grad)
        p.setPen(QPen(self._color, 1.6))
        p.drawPath(path)


class MetricRow(QWidget):
    def __init__(self, label: str, label_w: int = 86, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, theme.scaled(1), 0, theme.scaled(1))
        outer.setSpacing(0)

        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(theme.scaled(6))
        self._label = QLabel(label)
        self._label.setProperty("role", "mute")
        self._label.setFont(make_font(8.5))
        self._label.setFixedWidth(theme.scaled(label_w))
        self._value = QLabel("—")
        self._value.setFont(make_font(9.5, QFont.Weight.DemiBold))
        self._value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        top.addWidget(self._label)
        top.addWidget(self._value, 1)
        outer.addLayout(top)

        self._stat = QLabel("")
        self._stat.setProperty("role", "faint")
        self._stat.setFont(make_font(7))
        self._stat.setAlignment(Qt.AlignmentFlag.AlignRight)
        self._stat.setVisible(False)
        outer.addWidget(self._stat)

    def set_value(self, text: str, color: str | None = None) -> None:
        self._value.setText(text)
        self._value.setStyleSheet(f"color: {color};" if color else f"color: {theme.TXT};")

    def set_stat(self, text: str) -> None:
        if text:
            self._stat.setText(text)
            self._stat.setVisible(True)
        else:
            self._stat.setVisible(False)


class SectionCard(QFrame):
    def __init__(self, title: str, color: str, with_spark: bool = False,
                 with_bar: bool = True, fixed_max: float = 100.0,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Section")
        self._color = color
        lay = QVBoxLayout(self)
        lay.setContentsMargins(theme.scaled(12), theme.scaled(7), theme.scaled(12), theme.scaled(8))
        lay.setSpacing(theme.scaled(5))

        hdr = QHBoxLayout()
        hdr.setSpacing(theme.scaled(7))
        tick = QFrame()
        tick.setFixedSize(theme.scaled(3), theme.scaled(12))
        tick.setStyleSheet(f"background: {color}; border-radius: 1px;")
        title_lbl = QLabel(title.upper())
        title_lbl.setProperty("role", "title")
        title_lbl.setFont(make_font(8, QFont.Weight.Bold))
        hdr.addWidget(tick)
        hdr.addWidget(title_lbl)
        hdr.addStretch(1)
        self._hint = QLabel("")
        self._hint.setProperty("role", "faint")
        self._hint.setFont(make_font(8))
        hdr.addWidget(self._hint)
        lay.addLayout(hdr)

        self._bar: ProgressBar | None = None
        if with_bar:
            self._bar = ProgressBar(color)
            lay.addWidget(self._bar)

        self._spark: Sparkline | None = None
        if with_spark:
            self._spark = Sparkline(color, fixed_max=fixed_max)
            lay.addWidget(self._spark)

        self._rows: dict[str, MetricRow] = {}
        self._rows_lay = QVBoxLayout()
        self._rows_lay.setContentsMargins(0, theme.scaled(2), 0, 0)
        self._rows_lay.setSpacing(0)
        lay.addLayout(self._rows_lay)

    def add_row(self, key: str, label: str) -> None:
        row = MetricRow(label)
        self._rows[key] = row
        self._rows_lay.addWidget(row)

    def set(self, key: str, text: str, color: str | None = None) -> None:
        if key in self._rows:
            self._rows[key].set_value(text, color)

    def set_stat(self, key: str, text: str) -> None:
        if key in self._rows:
            self._rows[key].set_stat(text)

    def set_bar(self, pct: float, color: str | None = None) -> None:
        if self._bar is None:
            return
        if color:
            self._bar.set_color(color)
        self._bar.animate_to(pct)

    def push_spark(self, v) -> None:
        if self._spark is not None:
            self._spark.push(v)

    def set_hint(self, text: str) -> None:
        self._hint.setText(text)
