"""Icones vetoriais da interface, desenhados com QPainter.

Os glifos Unicode que faziam esse papel vinham cada um de uma fonte diferente,
com peso, tamanho e alinhamento desiguais: o de GPU e o de Telas eram o mesmo
caractere, e o do Controle nem existia em todas as maquinas. Desenhados aqui,
todos partem da mesma caixa de 16 x 16, com o mesmo traco, e ganham a cor que a
tela pedir.
"""
from __future__ import annotations

import math
from collections.abc import Callable

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen

_BOX = 16.0
"""Lado da caixa de desenho. Cada icone e' descrito nessas coordenadas."""


def paint(p: QPainter, name: str, rect: QRectF, color: str, stroke: float = 1.6) -> bool:
    """Desenha `name` dentro de `rect`, centralizado e mantendo a proporcao.

    Devolve False quando o nome nao existe, para quem chama poder cair num
    texto de reserva em vez de desenhar nada.
    """
    fn = _ICONS.get(name)
    if fn is None:
        return False
    side = min(rect.width(), rect.height())
    if side <= 0:
        return True
    escala = side / _BOX
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.translate(rect.center().x() - side / 2, rect.center().y() - side / 2)
    p.scale(escala, escala)
    # Traco constante em pixels de tela: sem dividir pela escala, um icone
    # maior sairia com a linha mais gorda, e os da barra lateral nao casariam
    # com os da barra de titulo.
    pen = QPen(QColor(color), stroke / escala, Qt.PenStyle.SolidLine,
               Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    fn(p, QColor(color))
    p.restore()
    return True


def names() -> tuple[str, ...]:
    return tuple(_ICONS)


def _fill(p: QPainter, color: QColor):
    p.save()
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(color)
    return p


def _dashboard(p: QPainter, c: QColor) -> None:
    for x, y in ((1.5, 1.5), (9.0, 1.5), (1.5, 9.0), (9.0, 9.0)):
        p.drawRoundedRect(QRectF(x, y, 5.5, 5.5), 1.4, 1.4)


def _cpu(p: QPainter, c: QColor) -> None:
    p.drawRoundedRect(QRectF(3.5, 3.5, 9.0, 9.0), 1.6, 1.6)
    for a in (6.0, 10.0):
        p.drawLine(QPointF(a, 3.5), QPointF(a, 1.5))
        p.drawLine(QPointF(a, 12.5), QPointF(a, 14.5))
        p.drawLine(QPointF(3.5, a), QPointF(1.5, a))
        p.drawLine(QPointF(12.5, a), QPointF(14.5, a))
    _fill(p, c)
    p.drawRoundedRect(QRectF(6.4, 6.4, 3.2, 3.2), 0.6, 0.6)
    p.restore()


def _gpu(p: QPainter, c: QColor) -> None:
    p.drawRoundedRect(QRectF(1.5, 3.5, 13.0, 8.5), 1.6, 1.6)
    p.drawEllipse(QPointF(6.5, 7.75), 2.4, 2.4)
    p.drawLine(QPointF(10.5, 6.5), QPointF(12.5, 6.5))
    p.drawLine(QPointF(10.5, 9.0), QPointF(12.5, 9.0))
    p.drawLine(QPointF(3.0, 12.0), QPointF(3.0, 14.5))
    p.drawLine(QPointF(3.0, 14.5), QPointF(8.0, 14.5))


def _memory(p: QPainter, c: QColor) -> None:
    p.drawRoundedRect(QRectF(1.5, 4.0, 13.0, 7.0), 1.2, 1.2)
    for x in (5.0, 8.0, 11.0):
        p.drawLine(QPointF(x, 6.2), QPointF(x, 8.8))
    for x in (4.0, 8.0, 12.0):
        p.drawLine(QPointF(x, 11.0), QPointF(x, 13.0))


def _network(p: QPainter, c: QColor) -> None:
    for r in (4.2, 7.6):
        p.drawArc(QRectF(8.0 - r, 12.5 - r, 2 * r, 2 * r), 45 * 16, 90 * 16)
    _fill(p, c)
    p.drawEllipse(QPointF(8.0, 12.6), 1.4, 1.4)
    p.restore()


def _sensors(p: QPainter, c: QColor) -> None:
    p.drawRoundedRect(QRectF(6.4, 1.5, 3.2, 8.6), 1.6, 1.6)
    p.drawEllipse(QPointF(8.0, 12.2), 2.6, 2.6)
    _fill(p, c)
    p.drawEllipse(QPointF(8.0, 12.2), 1.1, 1.1)
    p.drawRect(QRectF(7.4, 6.0, 1.2, 5.0))
    p.restore()


def _processes(p: QPainter, c: QColor) -> None:
    for y in (4.0, 8.0, 12.0):
        p.drawLine(QPointF(5.5, y), QPointF(14.0, y))
    _fill(p, c)
    for y in (4.0, 8.0, 12.0):
        p.drawEllipse(QPointF(2.6, y), 1.1, 1.1)
    p.restore()


def _benchmark(p: QPainter, c: QColor) -> None:
    p.drawEllipse(QPointF(8.0, 9.4), 5.4, 5.4)
    p.drawLine(QPointF(8.0, 4.0), QPointF(8.0, 2.0))
    p.drawLine(QPointF(6.0, 2.0), QPointF(10.0, 2.0))
    p.drawLine(QPointF(8.0, 9.4), QPointF(10.6, 6.8))


def _launcher(p: QPainter, c: QColor) -> None:
    path = QPainterPath()
    path.moveTo(4.2, 2.6)
    path.lineTo(13.4, 8.0)
    path.lineTo(4.2, 13.4)
    path.closeSubpath()
    fundo = QColor(c)
    fundo.setAlpha(70)
    p.setBrush(fundo)
    p.drawPath(path)


def _displays(p: QPainter, c: QColor) -> None:
    p.drawRoundedRect(QRectF(1.5, 2.5, 13.0, 9.0), 1.6, 1.6)
    p.drawLine(QPointF(8.0, 11.5), QPointF(8.0, 14.0))
    p.drawLine(QPointF(5.0, 14.0), QPointF(11.0, 14.0))


def _gamepad(p: QPainter, c: QColor) -> None:
    p.drawRoundedRect(QRectF(1.5, 4.5, 13.0, 7.5), 3.6, 3.6)
    p.drawLine(QPointF(3.6, 8.25), QPointF(6.6, 8.25))
    p.drawLine(QPointF(5.1, 6.75), QPointF(5.1, 9.75))
    _fill(p, c)
    p.drawEllipse(QPointF(10.3, 7.2), 1.0, 1.0)
    p.drawEllipse(QPointF(12.2, 9.3), 1.0, 1.0)
    p.restore()


def _settings(p: QPainter, c: QColor) -> None:
    p.drawEllipse(QPointF(8.0, 8.0), 2.3, 2.3)
    for i in range(8):
        ang = math.radians(i * 45)
        dx, dy = math.cos(ang), math.sin(ang)
        p.drawLine(QPointF(8.0 + dx * 4.4, 8.0 + dy * 4.4),
                   QPointF(8.0 + dx * 6.6, 8.0 + dy * 6.6))


def _minimize(p: QPainter, c: QColor) -> None:
    p.drawLine(QPointF(3.0, 8.5), QPointF(13.0, 8.5))


def _maximize(p: QPainter, c: QColor) -> None:
    p.drawRoundedRect(QRectF(3.5, 3.5, 9.0, 9.0), 1.2, 1.2)


def _restore(p: QPainter, c: QColor) -> None:
    p.drawRoundedRect(QRectF(2.5, 5.5, 8.0, 8.0), 1.2, 1.2)
    path = QPainterPath()
    path.moveTo(5.5, 5.5)
    path.lineTo(5.5, 2.5)
    path.lineTo(13.5, 2.5)
    path.lineTo(13.5, 10.5)
    path.lineTo(10.5, 10.5)
    p.drawPath(path)


def _close(p: QPainter, c: QColor) -> None:
    p.drawLine(QPointF(4.0, 4.0), QPointF(12.0, 12.0))
    p.drawLine(QPointF(12.0, 4.0), QPointF(4.0, 12.0))


def _more(p: QPainter, c: QColor) -> None:
    _fill(p, c)
    for x in (3.4, 8.0, 12.6):
        p.drawEllipse(QPointF(x, 8.0), 1.3, 1.3)
    p.restore()


def _chevron_down(p: QPainter, c: QColor) -> None:
    path = QPainterPath()
    path.moveTo(3.5, 6.0)
    path.lineTo(8.0, 10.5)
    path.lineTo(12.5, 6.0)
    p.drawPath(path)


def _chevron_up(p: QPainter, c: QColor) -> None:
    path = QPainterPath()
    path.moveTo(3.5, 10.0)
    path.lineTo(8.0, 5.5)
    path.lineTo(12.5, 10.0)
    p.drawPath(path)


def _check(p: QPainter, c: QColor) -> None:
    path = QPainterPath()
    path.moveTo(3.2, 8.4)
    path.lineTo(6.6, 11.6)
    path.lineTo(12.8, 4.8)
    p.drawPath(path)


_ICONS: dict[str, Callable[[QPainter, QColor], None]] = {
    "dashboard": _dashboard, "cpu": _cpu, "gpu": _gpu, "memory": _memory,
    "network": _network, "sensors": _sensors, "processes": _processes,
    "benchmark": _benchmark, "launcher": _launcher, "displays": _displays,
    "gamepad": _gamepad, "settings": _settings, "minimize": _minimize,
    "maximize": _maximize, "restore": _restore, "close": _close, "more": _more,
    "chevron-down": _chevron_down, "chevron-up": _chevron_up, "check": _check,
}
