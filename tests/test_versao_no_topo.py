"""Versao no topo da janela, ao lado do nome, e no titulo da barra de tarefas.

No rodape da barra lateral ela ficava abaixo da lista inteira de telas, onde
ninguem olha; quem manda um print para perguntar alguma coisa tem que mandar
junto qual versao esta' rodando, sem ter que procurar.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("VANTAGE_NO_FILE_LOG", "1")

import pytest  # noqa: E402
from PySide6.QtGui import QColor  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

import vantage  # noqa: E402
from vantage import theme  # noqa: E402
from vantage.config import Settings  # noqa: E402
from vantage.ui import main_window  # noqa: E402

_qt = QApplication.instance() or QApplication([])


@pytest.fixture(scope="module")
def janela():
    from vantage.app import App

    app = App(_qt)
    w = app.window
    # A menor janela que o app aceita: se cabe nela, cabe em qualquer uma.
    w.resize(w.minimumWidth(), w.minimumHeight())
    w.show()
    _qt.processEvents()
    yield w
    w.hide()


def test_topo_mostra_exatamente_a_versao_do_pacote(janela):
    versao = janela.sidebar.versao
    assert versao.text() == f"v{vantage.__version__}"
    assert versao.isVisible()


def test_versao_fica_ao_lado_do_nome_e_acima_das_telas(janela):
    barra = janela.sidebar
    nome = barra._brand.geometry()
    versao = barra.versao.geometry()
    primeira_tela = min(b.geometry().top() for b in barra.buttons.values())
    assert versao.left() > nome.right()
    assert nome.top() <= versao.top() and versao.bottom() <= nome.bottom()
    assert versao.bottom() < primeira_tela


def test_versao_cabe_inteira_na_janela_estreita(janela):
    barra = janela.sidebar
    versao = barra.versao
    assert versao.width() >= versao.fontMetrics().horizontalAdvance(versao.text())
    assert versao.geometry().right() < barra.width()


def _luminancia(cor: QColor) -> float:
    def canal(v: int) -> float:
        v /= 255.0
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    return 0.2126 * canal(cor.red()) + 0.7152 * canal(cor.green()) + 0.0722 * canal(cor.blue())


def test_versao_tem_contraste_de_texto_sobre_a_barra(janela):
    """8 pt e' texto pequeno: o piso do WCAG e' 4.5:1, e o pedido foi aparecer.

    Le a cor que o rotulo pinta de fato, e nao a constante: trocar a tinta no
    main_window tem que cair aqui. A barra lateral e' pintada com SURFACE.
    """
    versao = janela.sidebar.versao
    tinta = versao.palette().color(versao.foregroundRole())
    la, lb = _luminancia(tinta), _luminancia(QColor(theme.SURFACE))
    assert (max(la, lb) + 0.05) / (min(la, lb) + 0.05) >= 4.5, tinta.name()


def test_titulo_da_janela_leva_a_versao(janela):
    """E' o que aparece na barra de tarefas e no Alt+Tab."""
    assert janela.windowTitle() == f"Vantage {vantage.__version__}"


def test_numero_vem_da_constante_e_nao_de_texto_fixo(monkeypatch):
    """A CI incrementa a constante; um numero escrito a mao envelheceria calado."""
    monkeypatch.setattr(main_window, "__version__", "9.8.7")

    class _Janela(QWidget):
        def __init__(self):
            super().__init__()
            self.app = type("A", (), {"settings": Settings()})()

        def show_view(self, _key):
            pass

    pai = _Janela()
    barra = main_window.Sidebar(pai)
    assert barra.versao.text() == "v9.8.7"
