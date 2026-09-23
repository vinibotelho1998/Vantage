"""Tela do controle: os relogios param quando ela some e voltam quando reaparece.

Nenhum controle e' consultado: a varredura de dispositivos e' um duble, e a
janela vive na plataforma offscreen, sem aparecer em tela nenhuma.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("VANTAGE_NO_FILE_LOG", "1")

from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget  # noqa: E402

import vantage.ui.views.gamepad as tela  # noqa: E402
from vantage.config import Settings  # noqa: E402

_qt = QApplication.instance() or QApplication([])


class _App:
    gamepad = None

    def __init__(self) -> None:
        self.settings = Settings()


def test_voltar_da_bandeja_religa_o_desenho_do_controle(monkeypatch):
    """Esconder a janela na bandeja esconde a tela junto e para os relogios. Na
    volta nada os religava: o desenho do controle ficava congelado ate' trocar
    de aba, e clicar na aba que continua aberta nao adiantava."""
    monkeypatch.setattr(tela.P, "list_pads", lambda: [])
    view = tela.GamepadView(_App())
    janela = QWidget()
    QVBoxLayout(janela).addWidget(view)
    try:
        janela.show()
        view.on_activate()
        _qt.processEvents()
        assert view._timer.isActive()

        janela.hide()
        _qt.processEvents()
        assert not view._timer.isActive()        # escondida, nao gasta nada

        janela.show()
        _qt.processEvents()
        assert view._timer.isActive()
        assert view._pads_timer.isActive()
    finally:
        janela.hide()
        janela.deleteLater()
