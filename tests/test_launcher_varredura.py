"""Procurar jogos instalados sem congelar a janela.

A varredura desce pelas pastas de jogo de cada disco e resolve cada atalho da
area de trabalho abrindo um PowerShell: segundos de trabalho. Rodando na thread
da interface, a janela ficava "Nao respondendo" ate' o fim. Aqui a varredura e'
um duble e nenhum disco e' percorrido.
"""
import os
import threading
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("VANTAGE_NO_FILE_LOG", "1")

from PySide6.QtWidgets import QApplication, QDialog  # noqa: E402

import vantage.ui.views.launcher as L  # noqa: E402
from vantage.config import Settings  # noqa: E402
from vantage.platform.gamescan import Achado  # noqa: E402

_qt = QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _sem_telas(monkeypatch):
    """A aba lista as telas ao redesenhar; aqui ela nao consulta monitor nenhum."""
    monkeypatch.setattr(L.D, "list_displays", lambda with_modes=False: [])


class _Cfg(Settings):
    def save(self) -> None:          # nada de tocar no settings.json
        self.salvou = True


class _App:
    def __init__(self):
        self.settings = _Cfg()
        self.session_history = []


class _Dialogo:
    """Aceita tudo sem abrir janela modal nenhuma."""

    def __init__(self, achados, parent=None):
        self._achados = achados

    def exec(self):
        return QDialog.DialogCode.Accepted

    def escolhidos(self):
        return list(self._achados)


def _esperar(condicao, prazo=5.0) -> None:
    fim = time.monotonic() + prazo
    while not condicao() and time.monotonic() < fim:
        _qt.processEvents()
        time.sleep(0.01)


def test_varredura_nao_roda_na_thread_da_interface(monkeypatch):
    thread_da_varredura = []
    liberar = threading.Event()

    def _scan(_ja_tenho):
        thread_da_varredura.append(threading.current_thread())
        liberar.wait(5.0)
        return [Achado("Forza Horizon 6", r"C:\Jogos\fh6\fh6.exe", "Steam")]

    monkeypatch.setattr(L.gamescan, "scan", _scan)
    monkeypatch.setattr(L, "EscolherJogos", _Dialogo)
    app = _App()
    view = L.LauncherView(app)

    view._procurar()
    _esperar(lambda: thread_da_varredura)
    assert thread_da_varredura[0] is not threading.main_thread()
    assert "procurando" in view.status.text()

    liberar.set()
    _esperar(lambda: app.settings.launch_items)
    assert [i["name"] for i in app.settings.launch_items] == ["Forza Horizon 6"]
    assert view.btn_scan.isEnabled()


def test_jogo_adicionado_durante_a_varredura_nao_entra_duas_vezes(monkeypatch):
    liberar = threading.Event()

    def _scan(_ja_tenho):
        liberar.wait(5.0)
        return [Achado("Forza Horizon 6", r"C:\Jogos\fh6\fh6.exe", "Steam")]

    monkeypatch.setattr(L.gamescan, "scan", _scan)
    monkeypatch.setattr(L, "EscolherJogos", _Dialogo)
    app = _App()
    view = L.LauncherView(app)

    view._procurar()
    app.settings.launch_items = [{"name": "FH6", "path": r"C:\Jogos\fh6\fh6.exe",
                                  "args": "", "target": "", "restore": True}]
    liberar.set()
    _esperar(lambda: view.btn_scan.isEnabled() and "procurando" not in view.status.text())

    assert len(app.settings.launch_items) == 1


def test_varredura_que_quebra_avisa_e_libera_o_botao(monkeypatch):
    def _scan(_ja_tenho):
        raise OSError("disco sumiu")

    monkeypatch.setattr(L.gamescan, "scan", _scan)
    view = L.LauncherView(_App())

    view._procurar()
    _esperar(lambda: "falhou" in view.status.text())

    assert "falhou" in view.status.text()
    assert view.btn_scan.isEnabled()


class _Tela:
    def __init__(self, monitor_id, nome, ativa, primaria):
        self.monitor_id, self.name = monitor_id, nome
        self.active, self.primary = ativa, primaria


def test_trocar_a_tela_do_big_picture_grava_e_redesenhar_nao_grava(monkeypatch):
    telas = [_Tela("uw", "ULTRAWIDE", True, True), _Tela("tv", "Beyond TV", False, False)]
    monkeypatch.setattr(L.D, "list_displays", lambda with_modes=False: list(telas))
    app = _App()
    view = L.LauncherView(app)
    app.settings.salvou = False

    view._refresh()
    view._refresh()
    assert app.settings.salvou is False            # redesenhar nao e' escolher

    indice = view.bp_tela.findData("screen:tv")
    view.bp_tela.setCurrentIndex(indice)
    assert app.settings.salvou is True
    assert app.settings.bigpicture_target == "screen:tv"
