"""Graficos vetoriais do Vantage.

Tudo desenhado a mao com QPainter para ter controle total sobre suavizacao e
densidade de informacao:

* interpolacao cubica monotona (Fritsch–Carlson): curva lisa que **nunca**
  inventa picos que nao existem nos dados;
* envelope min/max quando ha mais amostras que pixels, entao um spike de 1 frame
  continua visivel mesmo com 5 minutos de historico na tela;
* escala vertical com transicao amortecida, para o grafico nao "pular" a cada
  novo maximo.
"""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
)
from PySide6.QtWidgets import QSizePolicy, QWidget

from .. import theme

NAN = float("nan")


def monotone_tangents(ys: list[float]) -> list[float]:
    """Tangentes de Fritsch–Carlson para spline cubica monotona (x uniforme)."""
    n = len(ys)
    if n < 2:
        return [0.0] * n
    d = [ys[i + 1] - ys[i] for i in range(n - 1)]
    m = [0.0] * n
    m[0], m[-1] = d[0], d[-1]
    for i in range(1, n - 1):
        m[i] = 0.0 if d[i - 1] * d[i] <= 0 else (d[i - 1] + d[i]) / 2.0
    for i in range(n - 1):
        if d[i] == 0.0:
            m[i] = m[i + 1] = 0.0
            continue
        a, b = m[i] / d[i], m[i + 1] / d[i]
        s = a * a + b * b
        if s > 9.0:
            t = 3.0 / math.sqrt(s)
            m[i] = t * a * d[i]
            m[i + 1] = t * b * d[i]
    return m


def smooth_path(points: list[tuple[float, float]]) -> QPainterPath:
    """Caminho suave passando exatamente por todos os pontos."""
    path = QPainterPath()
    n = len(points)
    if n == 0:
        return path
    path.moveTo(*points[0])
    if n == 1:
        return path
    if n == 2:
        path.lineTo(*points[1])
        return path
    ys = [p[1] for p in points]
    m = monotone_tangents(ys)
    for i in range(n - 1):
        x0, y0 = points[i]
        x1, y1 = points[i + 1]
        dx = (x1 - x0) / 3.0
        path.cubicTo(QPointF(x0 + dx, y0 + m[i] / 3.0),
                     QPointF(x1 - dx, y1 - m[i + 1] / 3.0),
                     QPointF(x1, y1))
    return path


def linear_path(points: list[tuple[float, float]]) -> QPainterPath:
    path = QPainterPath()
    if not points:
        return path
    path.moveTo(*points[0])
    for p in points[1:]:
        path.lineTo(*p)
    return path


def envelope(values: list[float], columns: int) -> list[tuple[float, float, float]]:
    """Reduz a serie a `columns` colunas preservando (min, max, media) de cada bucket."""
    n = len(values)
    if n == 0 or columns <= 0:
        return []
    if n <= columns:
        return [(v, v, v) for v in values]
    step = n / columns
    out = []
    for i in range(columns):
        s = int(i * step)
        e = max(s + 1, int((i + 1) * step))
        chunk = values[s:e]
        out.append((min(chunk), max(chunk), sum(chunk) / len(chunk)))
    return out


def nice_step(span: float, target_lines: int = 4) -> float:
    """Passo 'redondo' para as linhas de grade."""
    if span <= 0:
        return 1.0
    raw = span / max(1, target_lines)
    mag = 10 ** math.floor(math.log10(raw))
    for mult in (1, 2, 2.5, 5, 10):
        if raw <= mag * mult:
            return mag * mult
    return mag * 10


def escolher_rotulos(itens: list[tuple[float, bool]], folga: float) -> list[bool]:
    """Quais rotulos de eixo cabem sem se sobrepor.

    `itens` traz (posicao, prioridade) e a resposta e' um booleano por item, na
    mesma ordem. Os prioritarios entram primeiro; o resto entra na ordem dada
    enquanto ficar a pelo menos `folga` de tudo que ja' entrou.
    """
    aceitos: list[float] = []
    resposta = [False] * len(itens)
    ordem = sorted(range(len(itens)), key=lambda i: (not itens[i][1], i))
    for i in ordem:
        y = itens[i][0]
        if all(abs(y - outro) >= folga for outro in aceitos):
            aceitos.append(y)
            resposta[i] = True
    return resposta


class Plot:
    """Uma linha do grafico: dados + estilo + estado de visibilidade."""

    __slots__ = ("key", "label", "color", "values", "visible", "unit", "width", "dashed")

    def __init__(self, key: str, label: str, color: str, unit: str = "",
                 width: float = 1.9, dashed: bool = False) -> None:
        self.key = key
        self.label = label
        self.color = color
        self.unit = unit
        self.width = width
        self.dashed = dashed
        self.values: list[float] = []
        self.visible = True


class TimeSeriesChart(QWidget):
    """Grafico de linhas temporal com grade, eixo, hover e escala amortecida."""

    def __init__(self, plots: list[Plot], y_max: float | None = 100.0,
                 y_min: float = 0.0, height: int = 180, unit: str = "%",
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._plots = plots
        self._fixed_max = y_max
        self._y_min = y_min
        self._unit = unit
        self._scale = y_max or 1.0
        self._target_scale = self._scale
        self._scale_settled = y_max is not None
        self._hover_x: float | None = None
        self._legend = True
        self._smooth = True
        self._fill = True
        self._grid = True
        self._glow = True
        self._seconds: float | None = None

        self.setMinimumHeight(theme.scaled(height))
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMouseTracking(True)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, False)

        self._anim = QTimer(self)
        self._anim.setInterval(33)
        self._anim.timeout.connect(self._tick_scale)

    def configure(self, smooth: bool = True, fill: bool = True, grid: bool = True,
                  glow: bool = True, legend: bool = True) -> None:
        self._smooth, self._fill, self._grid = smooth, fill, grid
        self._glow, self._legend = glow, legend
        self.update()

    def set_span(self, seconds: float | None) -> None:
        self._seconds = seconds

    def plot(self, key: str) -> Plot | None:
        return next((p for p in self._plots if p.key == key), None)

    def set_values(self, key: str, values: list[float]) -> None:
        p = self.plot(key)
        if p is not None:
            p.values = values

    def set_visible_plot(self, key: str, visible: bool) -> None:
        p = self.plot(key)
        if p is not None and p.visible != visible:
            p.visible = visible
            self.update()

    def toggle_plot(self, key: str) -> None:
        p = self.plot(key)
        if p is not None:
            p.visible = not p.visible
            self.update()

    def refresh(self) -> None:
        self._update_scale()
        self.update()

    def _visible_values(self) -> list[float]:
        out: list[float] = []
        for p in self._plots:
            if p.visible:
                out.extend(v for v in p.values if v == v)
        return out

    def _update_scale(self) -> None:
        if self._fixed_max is not None:
            self._scale = self._target_scale = self._fixed_max
            return
        vals = self._visible_values()
        peak = max(vals) if vals else 1.0
        target = max(peak * 1.18, 1e-6)
        step = nice_step(target - self._y_min)
        target = math.ceil(target / step) * step
        # primeira leitura (ou mudanca brutal de ordem de grandeza) entra sem animacao
        if not self._scale_settled or not (0.25 < target / max(self._scale, 1e-9) < 4.0):
            self._scale_settled = True
            self._scale = self._target_scale = target
            self._anim.stop()
            return
        if abs(target - self._target_scale) > 1e-9:
            self._target_scale = target
            if not self._anim.isActive():
                self._anim.start()

    def _tick_scale(self) -> None:
        delta = self._target_scale - self._scale
        if abs(delta) < self._target_scale * 0.004:
            self._scale = self._target_scale
            self._anim.stop()
        else:
            self._scale += delta * 0.22
        self.update()

    def mouseMoveEvent(self, event) -> None:
        self._hover_x = event.position().x()
        self.update()

    def leaveEvent(self, event) -> None:
        self._hover_x = None
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHints(QPainter.RenderHint.Antialiasing
                         | QPainter.RenderHint.TextAntialiasing)
        w, h = float(self.width()), float(self.height())
        pad_r = theme.scaled(46)
        pad_t = theme.scaled(16) if self._legend else theme.scaled(8)
        pad_b = theme.scaled(4)
        area = QRectF(0.0, pad_t, max(10.0, w - pad_r), max(10.0, h - pad_t - pad_b))

        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(theme.BG_SUNKEN))
        p.drawRoundedRect(QRectF(0, 0, w, h), theme.RADIUS_SM, theme.RADIUS_SM)

        span = max(1e-6, self._scale - self._y_min)
        if self._grid:
            self._paint_grid(p, area, w, span)

        columns = max(8, int(area.width()))
        active = [pl for pl in self._plots if pl.visible and len(pl.values) >= 2]
        # quanto mais linhas, mais leve o preenchimento; senao vira sopa de cores
        fill_alpha = (104, 104, 72, 46, 34)[min(len(active), 4)]
        series_points: dict[str, list[tuple[float, float]]] = {}
        for plot in active:
            pts = self._paint_plot(p, plot, area, span, columns, fill_alpha)
            if pts:
                series_points[plot.key] = pts

        if self._legend:
            self._paint_legend(p, w)
        self._paint_edge_labels(p, area, w, span)
        if self._hover_x is not None and series_points:
            self._paint_hover(p, area, span)

    def _y_of(self, value: float, area: QRectF, span: float) -> float:
        ratio = (value - self._y_min) / span
        return area.bottom() - max(0.0, min(1.06, ratio)) * area.height()

    def _paint_grid(self, p: QPainter, area: QRectF, w: float, span: float) -> None:
        step = nice_step(span)
        pen = QPen(QColor(theme.LINE), 1.0, Qt.PenStyle.SolidLine)
        p.setFont(QFont(theme.FONT_UI, max(6, theme.scaled(7))))
        value = self._y_min
        while value <= self._scale + 1e-9:
            y = self._y_of(value, area, span)
            p.setPen(pen)
            p.drawLine(QPointF(area.left(), y), QPointF(area.right(), y))
            p.setPen(QColor(theme.FAINT))
            label = f"{value:.0f}" if step >= 1 else f"{value:.1f}"
            p.drawText(QRectF(area.right() + 5, y - 8, w - area.right() - 6, 16),
                       int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                       f"{label}{self._unit}")
            value += step

    def _paint_plot(self, p: QPainter, plot: Plot, area: QRectF, span: float,
                    columns: int, fill_alpha: int = 100) -> list[tuple[float, float]]:
        values = [v for v in plot.values if v == v]
        if len(values) < 2:
            return []
        buckets = envelope(values, columns)
        n = len(buckets)
        dx = area.width() / max(1, n - 1)
        color = QColor(plot.color)

        pts = [(area.left() + i * dx, self._y_of(b[2], area, span))
               for i, b in enumerate(buckets)]
        path = smooth_path(pts) if self._smooth else linear_path(pts)

        # banda min/max: garante que picos curtos nao somem no downsample
        if len(values) > columns:
            top = [(area.left() + i * dx, self._y_of(b[1], area, span))
                   for i, b in enumerate(buckets)]
            bottom = [(area.left() + i * dx, self._y_of(b[0], area, span))
                      for i, b in enumerate(buckets)]
            band = QPainterPath()
            band.addPath(smooth_path(top) if self._smooth else linear_path(top))
            rev = list(reversed(bottom))
            band.lineTo(*rev[0])
            for pt in rev[1:]:
                band.lineTo(*pt)
            band.closeSubpath()
            fill = QColor(color)
            fill.setAlpha(max(20, int(fill_alpha * 0.46)))
            p.fillPath(band, fill)

        if self._fill and fill_alpha > 0:
            area_path = QPainterPath(path)
            area_path.lineTo(pts[-1][0], area.bottom())
            area_path.lineTo(pts[0][0], area.bottom())
            area_path.closeSubpath()
            grad = QLinearGradient(0, area.top(), 0, area.bottom())
            c0, c1 = QColor(color), QColor(color)
            c0.setAlpha(fill_alpha)
            c1.setAlpha(0)
            grad.setColorAt(0.0, c0)
            grad.setColorAt(1.0, c1)
            p.fillPath(area_path, grad)

        p.setBrush(Qt.BrushStyle.NoBrush)
        if self._glow:
            glow = QColor(color)
            glow.setAlpha(52)
            p.setPen(QPen(glow, plot.width * 3.4, Qt.PenStyle.SolidLine,
                          Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            p.drawPath(path)

        style = Qt.PenStyle.DashLine if plot.dashed else Qt.PenStyle.SolidLine
        p.setPen(QPen(color, plot.width, style, Qt.PenCapStyle.RoundCap,
                      Qt.PenJoinStyle.RoundJoin))
        p.drawPath(path)

        last = pts[-1]
        p.setPen(Qt.PenStyle.NoPen)
        halo = QColor(color)
        halo.setAlpha(70)
        p.setBrush(halo)
        p.drawEllipse(QPointF(*last), 5.0, 5.0)
        p.setBrush(color)
        p.drawEllipse(QPointF(*last), 2.4, 2.4)
        return pts

    def _paint_legend(self, p: QPainter, w: float) -> None:
        font = QFont(theme.FONT_UI, max(6, theme.scaled(7)), QFont.Weight.DemiBold)
        p.setFont(font)
        fm = QFontMetrics(font)
        x = theme.scaled(8)
        y = theme.scaled(11)
        for plot in self._plots:
            color = QColor(plot.color)
            if not plot.visible:
                color.setAlpha(70)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(color)
            p.drawRoundedRect(QRectF(x, y - 5, 9, 3), 1.5, 1.5)
            text = plot.label
            p.setPen(QColor(theme.MUTE if plot.visible else theme.FAINT))
            p.drawText(QPointF(x + 14, y + 1), text)
            x += 14 + fm.horizontalAdvance(text) + theme.scaled(12)
            if x > w - 40:
                break

    def _paint_edge_labels(self, p: QPainter, area: QRectF, w: float, span: float) -> None:
        if self._seconds is None:
            return
        p.setFont(QFont(theme.FONT_UI, max(6, theme.scaled(6.5))))
        p.setPen(QColor(theme.FAINT))
        p.drawText(QRectF(area.left() + 4, area.bottom() - 14, 120, 14),
                   int(Qt.AlignmentFlag.AlignLeft), f"-{self._seconds:.0f}s")
        p.drawText(QRectF(area.right() - 60, area.bottom() - 14, 56, 14),
                   int(Qt.AlignmentFlag.AlignRight), "agora")

    def _paint_hover(self, p: QPainter, area: QRectF, span: float) -> None:
        x = max(area.left(), min(area.right(), self._hover_x))
        ratio = (x - area.left()) / max(1.0, area.width())
        p.setPen(QPen(QColor(theme.LINE_HI), 1.0, Qt.PenStyle.DashLine))
        p.drawLine(QPointF(x, area.top()), QPointF(x, area.bottom()))

        rows: list[tuple[str, str, str]] = []
        for plot in self._plots:
            vals = [v for v in plot.values if v == v]
            if not plot.visible or len(vals) < 2:
                continue
            idx = min(len(vals) - 1, max(0, int(round(ratio * (len(vals) - 1)))))
            value = vals[idx]
            decimals = 0 if abs(value) >= 100 else 1
            rows.append((plot.color, plot.label, f"{value:.{decimals}f}{plot.unit or self._unit}"))
        if not rows:
            return

        font = QFont(theme.FONT_UI, max(6, theme.scaled(7)))
        p.setFont(font)
        fm = QFontMetrics(font)
        wid = max(fm.horizontalAdvance(f"{lb}  {vl}") for _, lb, vl in rows) + theme.scaled(26)
        hei = len(rows) * theme.scaled(14) + theme.scaled(10)
        bx = x + 10 if x + wid + 14 < area.right() else x - wid - 10
        by = max(area.top() + 2, min(area.bottom() - hei - 2, area.top() + 8))
        p.setPen(QPen(QColor(theme.LINE_HI), 1))
        p.setBrush(QColor(20, 26, 36, 240))
        p.drawRoundedRect(QRectF(bx, by, wid, hei), 6, 6)
        ty = by + theme.scaled(13)
        for color, label, value in rows:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(color))
            p.drawEllipse(QPointF(bx + theme.scaled(9), ty - 4), 2.6, 2.6)
            p.setPen(QColor(theme.MUTE))
            p.drawText(QPointF(bx + theme.scaled(17), ty), label)
            p.setPen(QColor(theme.TXT))
            p.drawText(QRectF(bx, ty - 11, wid - theme.scaled(8), 14),
                       int(Qt.AlignmentFlag.AlignRight), value)
            ty += theme.scaled(14)


class FrameTimeChart(QWidget):
    """Grafico dedicado a frametime: envelope, alvos de refresh e zonas de stutter."""

    TARGETS = ((1000 / 240, "240"), (1000 / 144, "144"), (1000 / 60, "60"), (1000 / 30, "30"))

    def __init__(self, height: int = 190, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._data: list[float] = []
        self._scale = 25.0
        self._target = 25.0
        self._hover_x: float | None = None
        self._smooth = True
        self.setMinimumHeight(theme.scaled(height))
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMouseTracking(True)
        self._anim = QTimer(self)
        self._anim.setInterval(33)
        self._anim.timeout.connect(self._tick)

    def configure(self, smooth: bool = True) -> None:
        self._smooth = smooth

    def _refresh_hz(self) -> float | None:
        """Taxa do monitor onde o widget esta: vira uma linha-alvo destacada."""
        screen = self.screen()
        if screen is None:
            return None
        hz = screen.refreshRate()
        return hz if 20 < hz < 1000 else None

    def set_data(self, frametimes: list[float]) -> None:
        self._data = frametimes
        if len(frametimes) >= 4:
            ordered = sorted(frametimes)
            p995 = ordered[min(len(ordered) - 1, int(len(ordered) * 0.995))]
            target = max(8.0, min(120.0, p995 * 1.35))
            if abs(target - self._target) / max(1.0, self._target) > 0.05:
                self._target = target
                if not self._anim.isActive():
                    self._anim.start()
        self.update()

    def _tick(self) -> None:
        delta = self._target - self._scale
        if abs(delta) < 0.15:
            self._scale = self._target
            self._anim.stop()
        else:
            self._scale += delta * 0.2
        self.update()

    def mouseMoveEvent(self, event) -> None:
        self._hover_x = event.position().x()
        self.update()

    def leaveEvent(self, event) -> None:
        self._hover_x = None
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHints(QPainter.RenderHint.Antialiasing
                         | QPainter.RenderHint.TextAntialiasing)
        w, h = float(self.width()), float(self.height())
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(theme.BG_SUNKEN))
        p.drawRoundedRect(QRectF(0, 0, w, h), theme.RADIUS_SM, theme.RADIUS_SM)

        pad_r = theme.scaled(40)
        area = QRectF(theme.scaled(4), theme.scaled(8),
                      max(10.0, w - pad_r), max(10.0, h - theme.scaled(16)))

        if len(self._data) < 3:
            p.setPen(QColor(theme.FAINT))
            p.setFont(QFont(theme.FONT_UI, max(7, theme.scaled(8))))
            p.drawText(self.rect(), int(Qt.AlignmentFlag.AlignCenter),
                       "aguardando frames do jogo…")
            return

        scale = max(1.0, self._scale)

        def y_of(ms: float) -> float:
            return area.bottom() - min(1.03, ms / scale) * area.height()

        refresh = self._refresh_hz()
        p.setFont(QFont(theme.FONT_UI, max(6, theme.scaled(6.5))))
        targets = [(ms, label, False) for ms, label in self.TARGETS
                   if not refresh or abs(1000 / ms - refresh) > 3]
        if refresh:
            targets.append((1000.0 / refresh, f"{refresh:.0f}", True))
        targets = [t for t in targets if t[0] <= scale]
        # Num monitor de 160 Hz as linhas de 144 e 165 ficam a menos de um
        # milissegundo dela, e os tres rotulos saiam escritos um por cima do
        # outro. A linha de cada alvo continua; o rotulo so' entra onde cabe,
        # e o do monitor tem preferencia.
        com_rotulo = escolher_rotulos([(y_of(ms), is_monitor) for ms, _l, is_monitor in targets],
                                      theme.scaled(11))
        for (ms, label, is_monitor), mostrar in zip(targets, com_rotulo, strict=True):
            y = y_of(ms)
            line_color = theme.FPS if is_monitor else theme.LINE
            p.setPen(QPen(QColor(line_color), 1.0, Qt.PenStyle.DashLine))
            p.drawLine(QPointF(area.left(), y), QPointF(area.right(), y))
            if not mostrar:
                continue
            p.setPen(QColor(theme.FPS if is_monitor else theme.FAINT))
            p.drawText(QRectF(area.right() + 4, y - 8, pad_r, 16),
                       int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                       f"{label}Hz")

        columns = max(16, int(area.width()))
        buckets = envelope(self._data, columns)
        n = len(buckets)
        dx = area.width() / max(1, n - 1)
        avg_pts = [(area.left() + i * dx, y_of(b[2])) for i, b in enumerate(buckets)]
        top_pts = [(area.left() + i * dx, y_of(b[1])) for i, b in enumerate(buckets)]
        low_pts = [(area.left() + i * dx, y_of(b[0])) for i, b in enumerate(buckets)]

        band = QPainterPath()
        band.addPath(linear_path(top_pts))
        for pt in reversed(low_pts):
            band.lineTo(*pt)
        band.closeSubpath()
        grad = QLinearGradient(0, area.top(), 0, area.bottom())
        c0, c1 = QColor(theme.FRAME), QColor(theme.FRAME)
        c0.setAlpha(120)
        c1.setAlpha(24)
        grad.setColorAt(0.0, c0)
        grad.setColorAt(1.0, c1)
        p.fillPath(band, grad)

        path = smooth_path(avg_pts) if self._smooth else linear_path(avg_pts)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(theme.FRAME).lighter(118), 1.7, Qt.PenStyle.SolidLine,
                      Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        p.drawPath(path)

        # marca visual dos frames realmente ruins
        median = sorted(self._data)[len(self._data) // 2]
        limit = max(50.0, median * 3.0)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(theme.BAD))
        for i, b in enumerate(buckets):
            if b[1] > limit:
                p.drawEllipse(QPointF(area.left() + i * dx, y_of(b[1])), 2.6, 2.6)

        if self._hover_x is not None:
            self._paint_hover(p, area, buckets, dx, y_of)

    def _paint_hover(self, p: QPainter, area: QRectF, buckets, dx: float, y_of) -> None:
        x = max(area.left(), min(area.right(), self._hover_x))
        idx = int(round((x - area.left()) / max(dx, 1e-6)))
        idx = max(0, min(len(buckets) - 1, idx))
        lo, hi, avg = buckets[idx]
        p.setPen(QPen(QColor(theme.LINE_HI), 1.0, Qt.PenStyle.DashLine))
        p.drawLine(QPointF(x, area.top()), QPointF(x, area.bottom()))
        text = f"{avg:.2f} ms · {1000 / avg:.0f} fps   (min {lo:.1f} / máx {hi:.1f})"
        font = QFont(theme.FONT_UI, max(6, theme.scaled(7)))
        p.setFont(font)
        wid = QFontMetrics(font).horizontalAdvance(text) + theme.scaled(16)
        bx = x + 8 if x + wid + 12 < area.right() else x - wid - 8
        p.setPen(QPen(QColor(theme.LINE_HI), 1))
        p.setBrush(QColor(20, 26, 36, 240))
        p.drawRoundedRect(QRectF(bx, area.top() + 2, wid, theme.scaled(20)), 6, 6)
        p.setPen(QColor(theme.TXT))
        p.drawText(QRectF(bx, area.top() + 2, wid, theme.scaled(20)),
                   int(Qt.AlignmentFlag.AlignCenter), text)


class Sparkline(QWidget):
    """Mini grafico inline usado dentro dos cards."""

    def __init__(self, color: str, height: int = 34, fixed_max: float | None = None,
                 parent: QWidget | None = None, from_zero: bool = False,
                 line_width: float = 1.6) -> None:
        super().__init__(parent)
        self._color = QColor(color)
        self._values: list[float] = []
        self._fixed_max = fixed_max
        self._from_zero = from_zero
        """Base no zero em vez do minimo da janela.

        Escala colada no minimo transforma variacao de 3 fps num tobogã. Para FPS
        o que interessa e' a queda de verdade, e ela so' aparece com o chao fixo.
        """
        self._line_width = line_width
        self._smooth = True
        self.setFixedHeight(theme.scaled(height))
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_values(self, values: list[float]) -> None:
        self._values = [v for v in values if v == v]
        self.update()

    def set_color(self, color: str) -> None:
        c = QColor(color)
        if c != self._color:
            self._color = c
            self.update()

    def configure(self, smooth: bool = True) -> None:
        self._smooth = smooth

    def paintEvent(self, _event) -> None:
        if len(self._values) < 2:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = float(self.width()), float(self.height())
        pad = 3.0
        buckets = envelope(self._values, max(8, int(w)))
        vals = [b[2] for b in buckets]
        if self._fixed_max is not None:
            hi, lo = self._fixed_max, 0.0
        elif self._from_zero:
            hi, lo = max(vals) * 1.12, 0.0
        else:
            hi, lo = max(vals), min(vals)
        rng = max(hi - lo, 1e-6)
        n = len(vals)
        dx = w / max(1, n - 1)
        pts = [(i * dx, (h - pad) - ((v - lo) / rng) * (h - 2 * pad))
               for i, v in enumerate(vals)]
        path = smooth_path(pts) if self._smooth else linear_path(pts)

        fill = QPainterPath(path)
        fill.lineTo(w, h)
        fill.lineTo(0, h)
        fill.closeSubpath()
        grad = QLinearGradient(0, 0, 0, h)
        c0, c1 = QColor(self._color), QColor(self._color)
        # Com o chao no zero a linha vive no alto, e o preenchimento cheio vira um
        # bloco solido; mais leve ele volta a ser fundo, nao figura.
        c0.setAlpha(46 if self._from_zero else 88)
        c1.setAlpha(0)
        grad.setColorAt(0.0, c0)
        grad.setColorAt(1.0, c1)
        p.fillPath(fill, grad)
        p.setBrush(Qt.BrushStyle.NoBrush)
        if self._line_width > 1.8:
            brilho = QColor(self._color)
            brilho.setAlpha(60)
            p.setPen(QPen(brilho, self._line_width * 2.6, Qt.PenStyle.SolidLine,
                          Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            p.drawPath(path)
        p.setPen(QPen(self._color, self._line_width, Qt.PenStyle.SolidLine,
                      Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        p.drawPath(path)


class Gauge(QWidget):
    """Arco radial com valor no centro; usado nos cards de CPU/GPU/RAM."""

    def __init__(self, color: str, size: int = 108, caption: str = "",
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._color = QColor(color)
        self._value = 0.0
        self._shown = 0.0
        self._caption = caption
        self._sub = ""
        self._size = size
        self._first = True
        self.setFixedSize(theme.scaled(size), theme.scaled(size))
        self._anim = QTimer(self)
        self._anim.setInterval(25)
        self._anim.timeout.connect(self._tick)

    def set_value(self, value: float | None, sub: str = "", color: str | None = None) -> None:
        self._value = 0.0 if value is None else max(0.0, min(100.0, float(value)))
        self._sub = sub
        if color:
            self._color = QColor(color)
        if self._first:
            self._first = False
            self._shown = self._value
        elif abs(self._shown - self._value) > 0.4 and not self._anim.isActive():
            self._anim.start()
        self.update()

    def _tick(self) -> None:
        delta = self._value - self._shown
        if abs(delta) < 0.4:
            self._shown = self._value
            self._anim.stop()
        else:
            self._shown += delta * 0.25
        self.update()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHints(QPainter.RenderHint.Antialiasing
                         | QPainter.RenderHint.TextAntialiasing)
        side = min(self.width(), self.height())
        thickness = max(5.0, side * 0.085)
        rect = QRectF(thickness / 2 + 1, thickness / 2 + 1,
                      side - thickness - 2, side - thickness - 2)
        start = 225 * 16
        total = -270 * 16

        p.setPen(QPen(QColor(theme.LINE), thickness, Qt.PenStyle.SolidLine,
                      Qt.PenCapStyle.RoundCap))
        p.drawArc(rect, start, total)

        span = int(total * self._shown / 100.0)
        if span:
            glow = QColor(self._color)
            glow.setAlpha(60)
            p.setPen(QPen(glow, thickness * 1.9, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawArc(rect, start, span)
            p.setPen(QPen(self._color, thickness, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawArc(rect, start, span)

        p.setPen(QColor(theme.TXT))
        f = QFont(theme.FONT_DISPLAY, max(11, int(side * 0.235)), QFont.Weight.Bold)
        p.setFont(f)
        p.drawText(QRectF(0, side * 0.28, side, side * 0.30),
                   int(Qt.AlignmentFlag.AlignCenter), f"{self._shown:.0f}%")
        if self._sub:
            p.setPen(QColor(theme.MUTE))
            p.setFont(QFont(theme.FONT_UI, max(6, int(side * 0.085))))
            p.drawText(QRectF(0, side * 0.56, side, side * 0.16),
                       int(Qt.AlignmentFlag.AlignCenter), self._sub)
        if self._caption:
            p.setPen(QColor(theme.FAINT))
            p.setFont(QFont(theme.FONT_UI, max(6, int(side * 0.075)), QFont.Weight.Bold))
            p.drawText(QRectF(0, side * 0.72, side, side * 0.14),
                       int(Qt.AlignmentFlag.AlignCenter), self._caption.upper())


class BarMeter(QWidget):
    """Barra horizontal animada com trilho e gradiente."""

    def __init__(self, color: str, height: int = 6, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._color = QColor(color)
        self._value = 0.0
        self._shown = 0.0
        self._first = True
        self.setFixedHeight(theme.scaled(height))
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._anim = QTimer(self)
        self._anim.setInterval(25)
        self._anim.timeout.connect(self._tick)

    def set_value(self, value: float | None, color: str | None = None) -> None:
        self._value = 0.0 if value is None else max(0.0, min(100.0, float(value)))
        if color:
            c = QColor(color)
            if c != self._color:
                self._color = c
        if self._first:
            self._first = False
            self._shown = self._value
        elif abs(self._shown - self._value) > 0.3 and not self._anim.isActive():
            self._anim.start()
        self.update()

    def _tick(self) -> None:
        delta = self._value - self._shown
        if abs(delta) < 0.3:
            self._shown = self._value
            self._anim.stop()
        else:
            self._shown += delta * 0.25
        self.update()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = float(self.width()), float(self.height())
        r = h / 2
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(theme.LINE))
        p.drawRoundedRect(QRectF(0, 0, w, h), r, r)
        fw = w * self._shown / 100.0
        if fw >= 1:
            grad = QLinearGradient(0, 0, w, 0)
            grad.setColorAt(0.0, self._color.darker(115))
            grad.setColorAt(1.0, self._color.lighter(125))
            p.setBrush(grad)
            p.drawRoundedRect(QRectF(0, 0, max(fw, 2 * r), h), r, r)


class Histogram(QWidget):
    """Distribuicao de FPS da sessao."""

    def __init__(self, color: str = theme.FPS, height: int = 130,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._color = QColor(color)
        self._centers: list[float] = []
        self._counts: list[int] = []
        self.setMinimumHeight(theme.scaled(height))
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set_data(self, centers: list[float], counts: list[int]) -> None:
        self._centers, self._counts = centers, counts
        self.update()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHints(QPainter.RenderHint.Antialiasing
                         | QPainter.RenderHint.TextAntialiasing)
        w, h = float(self.width()), float(self.height())
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(theme.BG_SUNKEN))
        p.drawRoundedRect(QRectF(0, 0, w, h), theme.RADIUS_SM, theme.RADIUS_SM)
        if not self._counts:
            p.setPen(QColor(theme.FAINT))
            p.setFont(QFont(theme.FONT_UI, max(7, theme.scaled(8))))
            p.drawText(self.rect(), int(Qt.AlignmentFlag.AlignCenter), "sem amostras")
            return
        pad_b = theme.scaled(16)
        top = theme.scaled(8)
        peak = max(self._counts) or 1
        n = len(self._counts)
        bw = w / n
        for i, c in enumerate(self._counts):
            bh = (h - pad_b - top) * (c / peak)
            color = QColor(theme.fps_color(self._centers[i]))
            color.setAlpha(215)
            p.setBrush(color)
            p.drawRoundedRect(QRectF(i * bw + 1, h - pad_b - bh, max(1.0, bw - 2), bh), 2, 2)
        p.setPen(QColor(theme.FAINT))
        p.setFont(QFont(theme.FONT_UI, max(6, theme.scaled(6.5))))
        p.drawText(QRectF(4, h - pad_b, 80, pad_b), int(Qt.AlignmentFlag.AlignLeft),
                   f"{self._centers[0]:.0f} fps")
        p.drawText(QRectF(w - 84, h - pad_b, 80, pad_b), int(Qt.AlignmentFlag.AlignRight),
                   f"{self._centers[-1]:.0f} fps")


class PercentileChart(QWidget):
    """Curva percentil -> FPS: mostra em uma olhada o tamanho da cauda ruim."""

    def __init__(self, height: int = 140, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._points: list[tuple[float, float]] = []
        self.setMinimumHeight(theme.scaled(height))
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set_points(self, points: list[tuple[float, float]]) -> None:
        self._points = points
        self.update()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHints(QPainter.RenderHint.Antialiasing
                         | QPainter.RenderHint.TextAntialiasing)
        w, h = float(self.width()), float(self.height())
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(theme.BG_SUNKEN))
        p.drawRoundedRect(QRectF(0, 0, w, h), theme.RADIUS_SM, theme.RADIUS_SM)
        if len(self._points) < 3:
            p.setPen(QColor(theme.FAINT))
            p.setFont(QFont(theme.FONT_UI, max(7, theme.scaled(8))))
            p.drawText(self.rect(), int(Qt.AlignmentFlag.AlignCenter), "sem amostras")
            return
        pad = theme.scaled(18)
        area = QRectF(pad, theme.scaled(8), w - pad - theme.scaled(34), h - theme.scaled(26))
        fps = [v for _, v in self._points]
        lo, hi = min(fps) * 0.94, max(fps) * 1.04
        rng = max(hi - lo, 1e-6)
        pts = [(area.left() + area.width() * (i / (len(self._points) - 1)),
                area.bottom() - (v - lo) / rng * area.height())
               for i, (_q, v) in enumerate(self._points)]
        path = smooth_path(pts)
        fill = QPainterPath(path)
        fill.lineTo(pts[-1][0], area.bottom())
        fill.lineTo(pts[0][0], area.bottom())
        fill.closeSubpath()
        grad = QLinearGradient(0, area.top(), 0, area.bottom())
        c0, c1 = QColor(theme.FPS), QColor(theme.FPS)
        c0.setAlpha(80)
        c1.setAlpha(0)
        grad.setColorAt(0.0, c0)
        grad.setColorAt(1.0, c1)
        p.fillPath(fill, grad)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(theme.FPS), 1.9, Qt.PenStyle.SolidLine,
                      Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        p.drawPath(path)

        p.setFont(QFont(theme.FONT_UI, max(6, theme.scaled(6.5))))
        p.setPen(QColor(theme.FAINT))
        for label, ratio in (("0.1%", 0.02), ("25%", 0.25), ("50%", 0.5),
                             ("75%", 0.75), ("99%", 0.98)):
            x = area.left() + area.width() * ratio
            p.drawText(QRectF(x - 20, area.bottom() + 2, 40, 14),
                       int(Qt.AlignmentFlag.AlignCenter), label)
        p.drawText(QRectF(area.right() + 3, area.top() - 4, theme.scaled(34), 14),
                   int(Qt.AlignmentFlag.AlignLeft), f"{hi:.0f}")
        p.drawText(QRectF(area.right() + 3, area.bottom() - 10, theme.scaled(34), 14),
                   int(Qt.AlignmentFlag.AlignLeft), f"{lo:.0f}")


class CoreGrid(QWidget):
    """Grade de nucleos da CPU com uso por thread (estilo gerenciador de tarefas)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._values: list[float] = []
        self._clocks: list[float] = []
        self._columns = 8
        self.setMinimumHeight(theme.scaled(120))
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set_data(self, values: list[float], clocks: list[float] | None = None) -> None:
        self._values = list(values or [])
        self._clocks = list(clocks or [])
        n = len(self._values)
        self._columns = 4 if n <= 8 else (6 if n <= 12 else 8)
        self.update()

    def paintEvent(self, _event) -> None:
        if not self._values:
            return
        p = QPainter(self)
        p.setRenderHints(QPainter.RenderHint.Antialiasing
                         | QPainter.RenderHint.TextAntialiasing)
        n = len(self._values)
        cols = self._columns
        rows = math.ceil(n / cols)
        gap = theme.scaled(5)
        cw = (self.width() - gap * (cols - 1)) / cols
        ch = (self.height() - gap * (rows - 1)) / rows
        # O corpo da letra acompanha o tile: numa janela larga os blocos sao
        # grandes e um "36%" de 6,5 pt virava um pontinho perdido no meio.
        corpo = max(6.5, min(11.0, ch * 0.22))
        font = QFont(theme.FONT_UI, round(corpo), QFont.Weight.DemiBold)
        fonte_clock = QFont(theme.FONT_UI, round(max(6.0, min(8.5, ch * 0.16))))
        p.setFont(font)
        for i, value in enumerate(self._values):
            r, c = divmod(i, cols)
            x, y = c * (cw + gap), r * (ch + gap)
            rect = QRectF(x, y, cw, ch)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(theme.BG_SUNKEN))
            p.drawRoundedRect(rect, 5, 5)
            fill_h = (ch - 2) * max(0.0, min(100.0, value)) / 100.0
            color = QColor(theme.load_color(value))
            color.setAlpha(190)
            p.setBrush(color)
            p.drawRoundedRect(QRectF(x + 1, y + ch - 1 - fill_h, cw - 2, fill_h), 4, 4)
            p.setFont(font)
            p.setPen(QColor(theme.TXT if value < 55 else theme.BG))
            p.drawText(rect, int(Qt.AlignmentFlag.AlignCenter), f"{value:.0f}%")
            if i < len(self._clocks) and self._clocks[i]:
                covered = fill_h > ch - theme.scaled(15)
                p.setFont(fonte_clock)
                p.setPen(QColor(theme.BG if covered else theme.FAINT))
                p.drawText(QRectF(x, y + 2, cw, 12), int(Qt.AlignmentFlag.AlignCenter),
                           f"{self._clocks[i] / 1000:.1f}G")
