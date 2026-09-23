"""Rotulo que cede com reticencias, e a linha de metrica que o usa do lado certo.

Em janela estreita o QLabel comum nao encolhe: o texto atravessa o vizinho ou
some pela borda, e "min 58 . med 65 . max 7" passa a mentir um numero. O
rotulo elidivel encolhe ate' uma reticencia e deixa o valor inteiro.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QPixmap  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402

from vantage.ui.components import Card, ElideLabel, MetricRow, StatTile  # noqa: E402

_app = QApplication.instance() or QApplication([])

_LONGO = "Frequencia da memoria do sistema em megahertz"


def test_largura_minima_e_de_uma_reticencia():
    lb = ElideLabel(_LONGO)
    assert lb.minimumSizeHint().width() < lb.sizeHint().width()
    assert lb.minimumSizeHint().width() <= lb.fontMetrics().horizontalAdvance("…") + 4


def test_altura_minima_continua_a_do_texto():
    lb = ElideLabel(_LONGO)
    assert lb.minimumSizeHint().height() == QLabel.minimumSizeHint(lb).height()


def test_apertado_pinta_sem_estourar_e_com_reticencia():
    lb = ElideLabel(_LONGO)
    lb.resize(40, 20)
    pix = QPixmap(lb.size())
    lb.render(pix)
    elidido = lb.fontMetrics().elidedText(lb.text(), Qt.TextElideMode.ElideRight, 40)
    assert elidido.endswith("…")
    assert len(elidido) < len(_LONGO)


def test_linha_de_metrica_cede_o_rotulo_e_nao_o_valor():
    row = MetricRow(_LONGO)
    row.set("6000 MHz")
    assert isinstance(row._label, ElideLabel)
    assert not isinstance(row._value, ElideLabel)
    assert row._value.minimumSizeHint().width() == row._value.sizeHint().width()


def test_tile_e_card_usam_rotulos_que_cedem():
    tile = StatTile("CPU temp", "C")
    assert isinstance(tile._sub, ElideLabel)
    assert isinstance(tile._caption, ElideLabel)
    card = Card("Titulo", hint="arraste as telas; elas colam nas vizinhas")
    assert isinstance(card._hint, ElideLabel)
