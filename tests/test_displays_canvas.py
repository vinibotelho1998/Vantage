"""Arraste das telas no mapa da aba Telas.

O retangulo tem de acompanhar o cursor. Ja' nao acompanhava: a escala do
desenho era recalculada a cada movimento, entao afastar uma tela aumentava os
limites, encolhia tudo e o retangulo fugia do ponteiro: parecia que sumia.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QPointF, QRect  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from vantage.ui.views.displays import ArrangeCanvas  # noqa: E402

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


# ── seletor de resolucao ─────────────────────────────────────────────────────
def test_indice_por_valor_e_nao_por_identidade():
    """QComboBox.findData compara payload Python por identidade.

    Procurar (1920, 1080) devolvia -1 mesmo com o item guardando exatamente
    (1920, 1080). O seletor ficava no primeiro item (o maior modo da lista)
    e numa TV 4K isso oferecia "4096 x 2160 escalonada" com o painel em 3840 x
    2160 nativo. Aplicar sem perceber esticava a imagem.
    """
    from PySide6.QtWidgets import QComboBox

    from vantage.ui.views.displays import _index_of

    box = QComboBox()
    for wh in ((2560, 1440), (1920, 1200), (1920, 1080), (1280, 720)):
        box.addItem(f"{wh[0]} x {wh[1]}", wh)

    assert _index_of(box, (1920, 1080)) == 2
    assert _index_of(box, (2560, 1440)) == 0
    assert _index_of(box, (800, 600)) == -1


def test_seletor_nasce_no_modo_atual_e_nao_no_maior():

    from vantage.ui.views.displays import _combo, _index_of

    itens = [("4096 x 2160   escalonada", (4096, 2160)),
             ("3840 x 2160   nativa", (3840, 2160))]
    box = _combo(itens, (3840, 2160))
    assert box.currentData() == (3840, 2160)
    assert _index_of(box, box.currentData()) == 1


# ── telas desligadas no mapa ─────────────────────────────────────────────────
class _Disp:
    def __init__(self, mid, nome, ativa, primaria=False, pos=(0, 0), modo=(1920, 1080)):
        from vantage.platform.displays import Mode
        self.monitor_id = mid
        self.name = nome
        self.active = ativa
        self.primary = primaria
        self.position = pos
        self.native = modo
        self.mode = Mode(modo[0], modo[1], 60, 32) if ativa else None


def test_tela_desligada_aparece_no_mapa():
    """Sumir e' ambiguo: desligada, desconectada, ou o app nao viu?"""
    c = ArrangeCanvas()
    c.resize(600, 300)
    c.load([_Disp("uw", "ULTRAWIDE", True, True, (0, 0), (3440, 1440)),
            _Disp("tv", "Beyond TV", False, modo=(3840, 2160))])
    assert "tv" in c.rects
    assert "tv" in c.apagadas
    assert "uw" not in c.apagadas


def test_desligada_nao_pode_ser_arrastada():
    """Ela nao tem posicao no desktop; a do mapa e' so' de desenho."""
    c = ArrangeCanvas()
    c.resize(600, 300)
    c.load([_Disp("uw", "ULTRAWIDE", True, True, (0, 0), (3440, 1440)),
            _Disp("tv", "Beyond TV", False, modo=(3840, 2160))])
    centro = c._to_screen(c.rects["tv"]).center()
    c.mousePressEvent(_Evento(centro.x(), centro.y()))
    assert c._drag != "tv"


def test_posicao_inventada_nao_vai_para_o_windows():
    """Mandar a posicao de desenho criaria um arranjo que ninguem pediu."""
    c = ArrangeCanvas()
    c.resize(600, 300)
    c.load([_Disp("uw", "ULTRAWIDE", True, True, (0, 0), (3440, 1440)),
            _Disp("tv", "Beyond TV", False, modo=(3840, 2160))])
    assert "tv" not in c.positions()
    assert "uw" in c.positions()


def test_mapa_so_com_telas_desligadas_nao_quebra():
    c = ArrangeCanvas()
    c.resize(600, 300)
    c.load([_Disp("tv", "Beyond TV", False, modo=(3840, 2160))])
    c.repaint()
    assert c.positions() == {}
