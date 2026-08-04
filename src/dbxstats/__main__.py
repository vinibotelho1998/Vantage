"""Ponto de entrada do DBX Stats."""
from __future__ import annotations

import subprocess
import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication, QIcon
from PySide6.QtWidgets import QApplication

from . import __version__, log, paths
from .platform import win


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
        "O DBX Stats precisa ser executado como administrador para ler os sensores "
        "de CPU, GPU e placa-mae e para capturar FPS dos jogos.\n\n"
        "Feche e abra de novo com o botao direito > Executar como administrador.",
        "DBX Stats - permissao necessaria",
        0x10)


def main() -> int:
    log.setup()
    if not win.is_admin():
        if _elevate():
            return 0
        _require_admin_warning()
        return 1

    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    qt = QApplication(sys.argv)
    qt.setApplicationName("DBX Stats")
    qt.setApplicationVersion(__version__)
    qt.setOrganizationName("DBX")
    icon = paths.asset("icon.ico")
    if icon.exists():
        qt.setWindowIcon(QIcon(str(icon)))

    from .app import App
    return App(qt).run()


if __name__ == "__main__":
    raise SystemExit(main())
