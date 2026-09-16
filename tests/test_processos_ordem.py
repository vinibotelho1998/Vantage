"""Ordenacao da lista de processos.

Antes so' dava para alternar entre CPU e memoria, num botao que escondia o
criterio. Quem procura "o que esta' comendo a RAM" pensa na coluna.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from vantage.config import Settings  # noqa: E402
from vantage.sensors.procs import ProcessMonitor, ProcInfo  # noqa: E402
from vantage.ui.views.processes import _ORDENS, _chave_ordem  # noqa: E402

_app = QApplication.instance() or QApplication([])

_LISTA = [
    ProcInfo(pid=300, name="zeta.exe", cpu=1.0, ram_mb=900.0, threads=4),
    ProcInfo(pid=100, name="alpha.exe", cpu=50.0, ram_mb=100.0, threads=40),
    ProcInfo(pid=200, name="Meio.exe", cpu=10.0, ram_mb=500.0, threads=12),
]


def _ordenado(criterio: str, desc: bool) -> list[str]:
    return [p.name for p in sorted(_LISTA, key=_chave_ordem(criterio), reverse=desc)]


def test_cada_coluna_ordena_pelo_seu_numero():
    assert _ordenado("cpu", True)[0] == "alpha.exe"
    assert _ordenado("ram", True)[0] == "zeta.exe"
    assert _ordenado("threads", True)[0] == "alpha.exe"
    assert _ordenado("pid", False)[0] == "alpha.exe"


def test_nome_ignora_maiuscula():
    """Sem isso "Meio.exe" apareceria antes de "alpha.exe", que ninguem espera."""
    assert _ordenado("name", False) == ["alpha.exe", "Meio.exe", "zeta.exe"]


def test_criterio_desconhecido_cai_na_cpu():
    """Configuracao velha ou coluna nova nao pode deixar a lista sem ordem."""
    assert _ordenado("coluna_que_nao_existe", True)[0] == "alpha.exe"


def _view():
    class Fake:
        def __init__(self):
            self.settings = Settings.load()
            self.procs = ProcessMonitor()

    from vantage.ui.views.processes import ProcessesView
    return ProcessesView(Fake())


def test_clicar_de_novo_inverte_a_mesma_coluna():
    v = _view()
    v._ordenar_por(3)
    assert (v._ordem, v._desc) == ("ram", True)
    v._ordenar_por(3)
    assert (v._ordem, v._desc) == ("ram", False)


def test_numero_comeca_do_maior_e_nome_do_a():
    """Trocar de coluna tem de cair na direcao que a pessoa espera."""
    v = _view()
    v._ordenar_por(_ORDENS.index("ram"))
    assert v._desc is True
    v._ordenar_por(_ORDENS.index("name"))
    assert v._desc is False


def test_a_seta_marca_so_a_coluna_em_uso():
    v = _view()
    v._ordenar_por(3)
    marcados = [i for i in range(len(_ORDENS))
                if "▼" in v.table.horizontalHeaderItem(i).text()
                or "▲" in v.table.horizontalHeaderItem(i).text()]
    assert marcados == [3]
