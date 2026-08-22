"""Rodape da barra lateral: versao, sensores e captura.

Ele existe para responder "por que nao aparece nada" sem abrir log — que foi
exatamente a pergunta que apareceu quando os sensores nao subiram numa maquina.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("DBXSTATS_NO_FILE_LOG", "1")

from PySide6.QtWidgets import QApplication  # noqa: E402

from dbxstats import __version__  # noqa: E402
from dbxstats.ui.main_window import Sidebar  # noqa: E402

QApplication.instance() or QApplication([])


class _Lhm:
    def __init__(self, ready=True, error=""):
        self.ready = ready
        self.error = error


class _Fps:
    def __init__(self, status="capturando"):
        self.status = status


def _sidebar(lhm=None, fps=None):
    """Sidebar sem construir a janela inteira: so' o rodape interessa."""
    from dbxstats.ui.components import label

    s = Sidebar.__new__(Sidebar)
    app = type("A", (), {})()
    app.lhm = lhm
    app.fps = fps
    s._win = type("W", (), {})()
    s._win.app = app
    s.saude = label("")
    return s


def test_versao_do_pacote_aparece():
    """Sem numero de versao nao da' para saber o que a outra pessoa instalou."""
    assert __version__.count(".") == 2


def test_tudo_de_pe_nao_chama_atencao():
    s = _sidebar(_Lhm(ready=True), _Fps("capturando"))
    s.atualizar_saude()
    assert "Sensores: ok" in s.saude.text()
    assert "capturando" in s.saude.text()
    assert "color: #FF5C5C" not in s.saude.styleSheet()


def test_esperar_jogo_e_estado_normal():
    """Ficar quieto no desktop e' o comportamento certo da captura, nao falha."""
    s = _sidebar(_Lhm(ready=True), _Fps("aguardando um jogo"))
    s.atualizar_saude()
    assert "color: #FF5C5C" not in s.saude.styleSheet()


def test_sensor_caido_fica_vermelho_e_explica():
    """O caso da maquina sem .NET: nenhuma metrica e nenhuma pista na tela."""
    s = _sidebar(_Lhm(ready=False, error="Nao encontrei o .NET Desktop Runtime"),
                 _Fps("capturando"))
    s.atualizar_saude()
    assert "Sensores: falhou" in s.saude.text()
    assert "color: #FF5C5C" in s.saude.styleSheet()
    assert ".NET" in s.saude.toolTip()


def test_captura_parada_fica_vermelha():
    s = _sidebar(_Lhm(ready=True), _Fps("PresentMon nao conectou"))
    s.atualizar_saude()
    assert "color: #FF5C5C" in s.saude.styleSheet()


def test_sem_leitor_nenhum_nao_quebra():
    """App a meio caminho de subir nao pode derrubar a barra lateral."""
    s = _sidebar(None, None)
    s.atualizar_saude()
    assert "falhou" in s.saude.text()
