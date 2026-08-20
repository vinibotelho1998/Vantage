"""Arraste das telas no mapa da aba Telas.

O retangulo tem de acompanhar o cursor. Ja' nao acompanhava: a escala do
desenho era recalculada a cada movimento, entao afastar uma tela aumentava os
limites, encolhia tudo e o retangulo fugia do ponteiro — parecia que sumia.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QPointF, QRect                      # noqa: E402
from PySide6.QtWidgets import QApplication                             # noqa: E402

from dbxstats.ui.views.displays import ArrangeCanvas                    # noqa: E402

_app = QApplication.instance() or QApplication([])


class _Evento:
    def __init__(self, x: float, y: float):
        self._p = QPointF(x, y)

    def position(self) -> QPointF:
        return self._p


def _canvas() -> ArrangeCanvas:
    c = ArrangeCanvas()
    c.resize(600, 300)
    c.rects = {
        "ultrawide": QRect(0, 0, 3440, 1440),
        "tv": QRect(3440, 0, 3840, 2160),
    }
    c.names = {"ultrawide": "ULTRAWIDE", "tv": "Beyond TV"}
    c.primary = "ultrawide"
    return c


def _centro(c: ArrangeCanvas, key: str) -> QPoint:
    return c._to_screen(c.rects[key]).center()


def test_tela_segue_o_cursor_e_nao_encolhe():
    c = _canvas()
    tamanho = c.rects["tv"].size()
    inicio = _centro(c, "tv")
    c.mousePressEvent(_Evento(inicio.x(), inicio.y()))
    assert c._drag == "tv"

    escala = c._projection()[1]
    c.mouseMoveEvent(_Evento(inicio.x() + 60, inicio.y()))

    # A escala nao pode mudar no meio do arraste, e o tamanho nunca muda.
    assert c._projection()[1] == escala
    assert c.rects["tv"].size() == tamanho
    assert c.rects["tv"].left() > 3440


def test_arraste_longo_nao_acumula_erro():
    """Somar deltas a cada movimento ia deixando a tela para tras do ponteiro."""
    c = _canvas()
    inicio = _centro(c, "tv")
    c.mousePressEvent(_Evento(inicio.x(), inicio.y()))
    for passo in range(1, 41):
        c.mouseMoveEvent(_Evento(inicio.x() + passo, inicio.y() + passo))

    esperado = c._to_desktop(QPoint(inicio.x() + 40, inicio.y() + 40)) - c._grab
    # A colagem nas vizinhas pode ajustar; fora isso o destino e' o do cursor.
    assert abs(c.rects["tv"].left() - esperado.x()) <= 40
    assert abs(c.rects["tv"].top() - esperado.y()) <= 40


def test_soltar_devolve_a_projecao_viva():
    c = _canvas()
    inicio = _centro(c, "tv")
    c.mousePressEvent(_Evento(inicio.x(), inicio.y()))
    assert c._proj is not None
    c.mouseReleaseEvent(_Evento(inicio.x(), inicio.y()))
    assert c._proj is None
    assert c._drag is None


def test_primaria_volta_para_a_origem_ao_soltar():
    c = _canvas()
    inicio = _centro(c, "ultrawide")
    c.mousePressEvent(_Evento(inicio.x(), inicio.y()))
    c.mouseMoveEvent(_Evento(inicio.x() + 80, inicio.y() + 20))
    c.mouseReleaseEvent(_Evento(inicio.x() + 80, inicio.y() + 20))
    assert c.rects["ultrawide"].topLeft() == QPoint(0, 0)
