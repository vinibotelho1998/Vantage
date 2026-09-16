"""Faixa de KPI no topo das telas.

Ela nascia vazia em toda tela que nao chamasse show_only: CPU, GPU, Memoria,
Rede, Processos, Benchmark, Telas e Controle ficavam com uma faixa em branco.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from vantage.ui.components import KpiStrip  # noqa: E402

_app = QApplication.instance() or QApplication([])

_SPECS = [("cpu", "CPU", "%"), ("gpu", "GPU", "%"),
          ("ram", "RAM", "%"), ("temp", "Temp", "°C")]


def test_faixa_nasce_cheia():
    """Um widget recem-criado sem pai responde isHidden() verdadeiro.

    O filtro do layout usava isso, entao nenhum tile entrava no grid, e sem
    entrar no grid nenhum tile ganhava pai. A faixa nunca saia do zero.
    """
    faixa = KpiStrip(_SPECS, columns=4)
    assert faixa._grid.count() == len(_SPECS)


def test_show_only_esconde_o_que_a_maquina_nao_mede():
    faixa = KpiStrip(_SPECS, columns=4)
    faixa.show_only(["cpu", "ram"])
    assert faixa._grid.count() == 2
    assert faixa.tiles["gpu"].isHidden()
    assert not faixa.tiles["cpu"].isHidden()


def test_show_only_pode_ser_desfeito():
    faixa = KpiStrip(_SPECS, columns=4)
    faixa.show_only(["cpu"])
    faixa.show_only([k for k, _c, _u in _SPECS])
    assert faixa._grid.count() == len(_SPECS)


def test_chamar_duas_vezes_igual_nao_remonta():
    faixa = KpiStrip(_SPECS, columns=4)
    faixa.show_only(["cpu", "gpu"])
    antes = [faixa._grid.itemAt(i).widget() for i in range(faixa._grid.count())]
    faixa.show_only(["gpu", "cpu"])
    depois = [faixa._grid.itemAt(i).widget() for i in range(faixa._grid.count())]
    assert antes == depois


def test_valor_chega_ao_tile_certo():
    faixa = KpiStrip(_SPECS, columns=4)
    faixa.set("cpu", "42")
    assert "42" in faixa.tiles["cpu"]._value.text()
