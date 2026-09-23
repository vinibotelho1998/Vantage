"""Faixa de KPI sem tile orfao, linha de metrica que nunca corta o numero e
bandeja com todas as telas.

Tres defeitos de largura e um de menu. A faixa enchia a primeira linha e jogava
o resto na de baixo, deixando um tile sozinho numa linha inteira. A linha de
metrica espremia o valor alinhado a' direita e cortava os digitos da esquerda:
2745 MHz virava 745 MHz. E a bandeja listava so' parte das telas da janela.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from vantage.ui import tray  # noqa: E402
from vantage.ui.components import (  # noqa: E402
    ElideLabel,
    KpiStrip,
    MetricRow,
    colunas_equilibradas,
)
from vantage.ui.main_window import NAV_OCULTAS, VIEW_CLASSES  # noqa: E402

_app = QApplication.instance() or QApplication([])


def test_colunas_equilibradas_nao_deixam_tile_sozinho():
    assert colunas_equilibradas(8, 8) == 8
    assert colunas_equilibradas(8, 7) == 4
    assert colunas_equilibradas(7, 6) == 4
    assert colunas_equilibradas(5, 3) == 3
    assert colunas_equilibradas(3, 10) == 3
    assert colunas_equilibradas(4, 1) == 1


def test_faixa_de_sete_nasce_em_duas_linhas_equilibradas():
    """Antes do primeiro resize a faixa ja' nasce sem orfao."""
    specs = [(f"k{i}", f"K{i}", "") for i in range(7)]
    faixa = KpiStrip(specs, columns=6)
    linhas = {}
    for i in range(faixa._grid.count()):
        linha, _c, _rs, _cs = faixa._grid.getItemPosition(i)
        linhas[linha] = linhas.get(linha, 0) + 1
    assert sorted(linhas.values()) == [3, 4]


def test_linha_de_metrica_estreita_corta_o_rotulo_e_nao_o_valor():
    linha = MetricRow("Frequência do núcleo mais rápido")
    linha.set("2745 MHz")
    linha.setFixedWidth(200)
    linha.show()
    _app.processEvents()
    valor = linha._value
    assert valor.width() >= valor.fontMetrics().horizontalAdvance("2745 MHz")
    assert linha._label.texto_visivel() != linha._label.text()
    assert linha._label.texto_visivel().endswith("…")


def test_rotulo_que_encolhe_nao_impoe_largura_minima():
    rotulo = ElideLabel("um rotulo bem comprido que nao cabe")
    assert rotulo.minimumSizeHint().width() == 0
    assert rotulo.text() == "um rotulo bem comprido que nao cabe"


def test_bandeja_lista_todas_as_telas_na_ordem_da_barra():
    esperadas = [cls.key for cls in VIEW_CLASSES if cls.key not in NAV_OCULTAS]
    assert [chave for chave, _nome in tray._VIEWS] == esperadas
