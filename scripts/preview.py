"""Gera screenshots das telas sem abrir janela (usa QWidget.render)."""
from __future__ import annotations

import math
import os
import sys
import tempfile

os.environ["QT_QPA_PLATFORM"] = "windows"  # precisa da fonte real do sistema
# Dados isolados: script de desenvolvimento nunca pode gravar por cima do
# settings.json de verdade (ja' apagou atalhos de jogo uma vez).
os.environ.setdefault("VANTAGE_DATA_DIR",
                      os.path.join(tempfile.gettempdir(), "vantage-dev"))
os.environ.setdefault("VANTAGE_NO_FILE_LOG", "1")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "src"))
sys.path.insert(0, os.path.dirname(__file__))

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QColor, QPixmap  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402
from smoke_ui import StubApp, fake_snapshot  # noqa: E402

from vantage import theme  # noqa: E402
from vantage.ui import style  # noqa: E402
from vantage.ui.main_window import MainWindow  # noqa: E402


def main() -> int:
    qt = QApplication(sys.argv)
    qt.setStyleSheet(style.build_qss("cyan"))
    app = StubApp(qt)
    for i in range(240):
        for key, value in (
            ("cpu_pct", 38 + 26 * math.sin(i / 11) + 6 * math.sin(i / 2.3)),
            ("cpu_temp", 58 + 12 * math.sin(i / 13)),
            ("cpu_watts", 55 + 22 * math.sin(i / 9)),
            ("cpu_mhz", 4500 + 300 * math.sin(i / 9)),
            ("gpu_pct", 72 + 22 * math.sin(i / 7)),
            ("gpu_temp", 64 + 6 * math.sin(i / 15)),
            ("gpu_watts", 165 + 40 * math.sin(i / 5)),
            ("gpu_mhz", 2700 + 80 * math.sin(i / 4)),
            ("gpu_mem_mhz", 10501),
            ("vram_pct", 56 + 8 * math.sin(i / 13)),
            ("ram_pct", 52 + 6 * math.sin(i / 17)),
            ("swap_pct", 20 + 3 * math.sin(i / 21)),
            ("disk_r", 9e6 * abs(math.sin(i / 3))),
            ("disk_w", 3e6 * abs(math.sin(i / 5))),
            ("net_dl", 2.4e6 * abs(math.sin(i / 6))),
            ("net_ul", 4e5 * abs(math.sin(i / 4))),
            ("ping_ms", 18 + 6 * abs(math.sin(i / 2))),
            ("packet_loss", 0.0),
            ("fps", 142 + 18 * math.sin(i / 8)),
            ("fps_low1", 106 + 10 * math.sin(i / 8)),
        ):
            app.history.push(key, value)
            app.stats.update(key, value)

    root = os.path.dirname(os.path.dirname(__file__))
    out = os.path.join(root, "docs", "preview")
    images = os.path.join(root, "docs", "images")
    os.makedirs(out, exist_ok=True)
    os.makedirs(images, exist_ok=True)

    window = MainWindow(app)
    # Mostrada, mas fora da tela: sem passar pelo show() o Qt nao assenta os
    # layouts, e widgets criados depois da montagem (os cards da aba Telas, a
    # lista de unidades) saiam na imagem amontoados em cima do cabecalho.
    window.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    window.resize(1680, 960)
    window.show()
    data = fake_snapshot(5)

    def _mostrar(key: str) -> None:
        window.show_view(key)
        window.tick_system(data)
        window.tick_fps()
        window.tick_clock()
        # Mais de uma volta: o pedido de layout da pagina rolavel e' adiado, e
        # a area de rolagem so' redimensiona a pagina na volta seguinte.
        for _ in range(4):
            qt.processEvents()

    for key in window.views:
        _mostrar(key)
        _shot(window, os.path.join(out, f"{key}.png"))
        print("gerado", key)

    # A imagem "de jogos" do README e' a de benchmark, que e' onde moram o
    # frametime, os lows e o gargalo; a ultima tela do laco era o Controle.
    _mostrar("benchmark")
    _shot(window, os.path.join(images, "gaming.png"))
    _mostrar("dashboard")
    _shot(window, os.path.join(images, "panel.png"))

    from vantage.ui.overlay import GameOverlay
    from vantage.ui.settings import SettingsDialog

    overlay = GameOverlay(app)
    overlay.refresh()
    overlay.adjustSize()
    _shot(overlay, os.path.join(images, "overlay.png"))
    print("gerado overlay")

    dialog = SettingsDialog(app, 3)
    dialog.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    dialog.resize(620, 720)
    dialog.show()
    qt.processEvents()
    _shot(dialog, os.path.join(images, "settings.png"))
    print("gerado settings")
    return 0


def _shot(widget, path: str) -> None:
    pix = QPixmap(widget.size())
    pix.fill(QColor(theme.BG))
    widget.render(pix)
    pix.save(path)


if __name__ == "__main__":
    raise SystemExit(main())
