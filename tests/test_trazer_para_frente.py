"""A segunda copia pede, e a primeira aparece de verdade.

O pedido chega pela thread que espera o evento nomeado, que nao e' do Qt e nao
tem laco de eventos. A janela aqui e' um duble: nada aparece na tela.
"""
import os
import threading
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("VANTAGE_NO_FILE_LOG", "1")

from PySide6.QtWidgets import QApplication  # noqa: E402

from vantage.app import App  # noqa: E402

_qt = QApplication.instance() or QApplication([])


class _Janela:
    def __init__(self) -> None:
        self.chamadas: list[tuple[str, bool]] = []

    def _anotar(self, nome: str) -> None:
        self.chamadas.append((nome, threading.current_thread() is threading.main_thread()))

    def isMinimized(self) -> bool:
        return False

    def show(self) -> None:
        self._anotar("show")

    def raise_(self) -> None:
        self._anotar("raise")

    def activateWindow(self) -> None:
        self._anotar("activate")


def test_pedido_de_outra_thread_mostra_a_janela_na_thread_da_interface():
    """Sem objeto de contexto o singleShot nascia na thread do pedido, que nao tem
    laco de eventos, e nunca disparava: a segunda copia fechava dizendo que
    tinha trazido a primeira, e ela continuava escondida na bandeja."""
    app = App.__new__(App)
    app.qt = _qt
    app.window = _Janela()

    pedido = threading.Thread(target=app.trazer_para_frente, name="instancia-unica")
    pedido.start()
    pedido.join()
    fim = time.monotonic() + 3.0
    while len(app.window.chamadas) < 3 and time.monotonic() < fim:
        _qt.processEvents()
        time.sleep(0.01)

    assert app.window.chamadas == [("show", True), ("raise", True), ("activate", True)]
