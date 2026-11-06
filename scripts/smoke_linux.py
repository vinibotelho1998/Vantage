"""Inicializa, amostra e fecha o app com dados temporários."""
import os
import sys
import tempfile
import traceback
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from vantage.app import App


def main():
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["VANTAGE_DATA_DIR"] = str(Path(tmp) / "vantage")
        os.environ["XDG_CONFIG_HOME"] = str(Path(tmp) / "config")
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        qt = QApplication([])
        app = App(qt)
        errors = []

        def fail(exc, value, trace):
            traceback.print_exception(exc, value, trace)
            errors.append(value)
            qt.exit(1)

        sys.excepthook = fail

        def check():
            data = app.collector.snapshot()
            if not data:
                QTimer.singleShot(250, check)
                return
            assert data["ram_total"] > 0 and data["disk_total"] > 0
            assert 0 <= data["cpu_pct"] <= 100
            for view in app.window.views:
                app.show_view(view)
                app._tick_system()
                qt.processEvents()
            app.open_settings()
            print(f"{len(app.window.views)} telas, {len(app.lhm.tree())} sensores, {data['cpu_name']}")
            app.quit()

        app.boot()
        QTimer.singleShot(1500, check)
        QTimer.singleShot(15000, lambda: qt.exit(2))
        result = qt.exec()
        return result or int(bool(errors))


if __name__ == "__main__":
    raise SystemExit(main())
