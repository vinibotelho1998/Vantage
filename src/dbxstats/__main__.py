"""Ponto de entrada do DBX Stats."""
from __future__ import annotations

import subprocess
import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication

from . import log, paths
from .platform import win


def _elevate() -> bool:
    if paths.is_frozen():
        params = subprocess.list2cmdline(sys.argv[1:])
    else:
        params = subprocess.list2cmdline(["-m", "dbxstats", *sys.argv[1:]])
    return win.run_as_admin(sys.executable, params)


def main() -> int:
    log.setup()
    if not win.is_admin() and _elevate():
        return 0

    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    qt = QApplication(sys.argv)

    from .app import App
    return App(qt).run()


if __name__ == "__main__":
    raise SystemExit(main())
