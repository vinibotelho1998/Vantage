"""Diagnostico de visibilidade da janela no display real (sem admin)."""
from __future__ import annotations

import sys

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from dbxstats.app import App


def main() -> int:
    qt = QApplication(sys.argv)
    app = App(qt)
    app.boot()

    def report() -> None:
        p = app.panel
        scr = QApplication.primaryScreen()
        print("=== PAINEL ===")
        print("visible:", p.isVisible(), "minimized:", p.isMinimized())
        print("size:", p.size().width(), "x", p.size().height())
        print("pos:", p.pos().x(), p.pos().y())
        print("geometry:", p.geometry().getRect())
        print("frameGeometry:", p.frameGeometry().getRect())
        print("opacity:", p.windowOpacity())
        print("root size:", p._root.size().width(), "x", p._root.size().height())
        if scr:
            print("screen full:", scr.geometry().getRect())
            print("screen avail:", scr.availableGeometry().getRect())
            print("devicePixelRatio:", scr.devicePixelRatio())

    QTimer.singleShot(1500, report)
    QTimer.singleShot(5000, qt.quit)
    qt.exec()
    app.quit()
    print("done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
