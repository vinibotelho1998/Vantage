"""Ponto de entrada do Dbx Stats."""
from __future__ import annotations

import subprocess
import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication, QIcon
from PySide6.QtWidgets import QApplication

from . import __version__, log, paths

_log = log.get("main")
from .platform import win
from .platform.instancia import InstanciaUnica


def _elevate() -> bool:
    if paths.is_frozen():
        params = subprocess.list2cmdline(sys.argv[1:])
    else:
        params = subprocess.list2cmdline(["-m", "dbxstats", *sys.argv[1:]])
    return win.run_as_admin(sys.executable, params)


def _require_admin_warning() -> None:
    import ctypes
    ctypes.windll.user32.MessageBoxW(
        0,
        "O Dbx Stats precisa ser executado como administrador para ler os sensores "
        "de CPU, GPU e placa-mae e para capturar FPS dos jogos.\n\n"
        "Feche e abra de novo com o botao direito > Executar como administrador.",
        "Dbx Stats - permissao necessaria",
        0x10)


def _identidade_na_barra() -> None:
    """Da' ao processo uma identidade propria para o Windows.

    Sem isso a barra de tarefas agrupa a janela sob o executavel que hospeda o
    Python e mostra o icone DELE, nao o do app, e fixar na barra fixa a coisa
    errada. O identificador tem de ser definido antes de qualquer janela nascer;
    depois disso o Windows ja' decidiu.
    """
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Dbx.DbxStats")
    except Exception:                                    # noqa: BLE001
        pass          # em Windows antigo simplesmente nao existe; nao e' fatal


def main() -> int:
    log.setup()
    if not win.is_admin():
        if _elevate():
            return 0
        _require_admin_warning()
        return 1

    # Depois da elevacao, e nunca antes: o processo que apenas dispara a copia
    # elevada tambem passaria por aqui, tomaria a vaga e faria a copia de
    # verdade se recusar a abrir.
    guarda = InstanciaUnica()
    if not guarda.assumir():
        # Nao basta sair calado: quem clicou no atalho de novo concluiria que o
        # app parou de abrir. A copia que ja' esta' no ar aparece no lugar.
        InstanciaUnica.pedir_foco()
        _log.info("ja' havia uma copia aberta; trouxe ela para a frente")
        return 0

    _identidade_na_barra()
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    qt = QApplication(sys.argv)
    qt.setApplicationName("Dbx Stats")
    qt.setApplicationVersion(__version__)
    qt.setOrganizationName("Dbx")
    icon = paths.asset("icon.ico")
    if icon.exists():
        qt.setWindowIcon(QIcon(str(icon)))

    from .app import App
    app = App(qt)
    # A segunda copia pede foco por evento nomeado; quem responde e' a janela.
    guarda.ouvir(app.trazer_para_frente)
    try:
        return app.run()
    finally:
        guarda.liberar()


if __name__ == "__main__":
    raise SystemExit(main())
