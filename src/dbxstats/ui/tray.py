"""Icone na bandeja do sistema com menu de acoes rapidas."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from .. import theme

_VIEWS = [("dashboard", "Painel"), ("cpu", "CPU"),
          ("gpu", "GPU"), ("sensors", "Sensores"), ("benchmark", "Benchmark"),
          ("displays", "Telas"), ("gamepad", "Controle")]


def make_icon(accent: str) -> QIcon:
    px = QPixmap(64, 64)
    px.fill(Qt.GlobalColor.transparent)
    p = QPainter(px)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(theme.BG))
    p.drawRoundedRect(3, 3, 58, 58, 15, 15)
    base = 50
    bars = [(13, 20, theme.CPU), (25, 33, theme.GPU),
            (37, 15, theme.RAM), (49, 27, theme.accent_color(accent))]
    for x, h, col in bars:
        p.setBrush(QColor(col))
        p.drawRoundedRect(x, base - h, 8, h, 3, 3)
    p.end()
    return QIcon(px)


class Tray:
    def __init__(self, controller) -> None:
        self._ctl = controller
        self._icon = QSystemTrayIcon(make_icon(controller.settings.accent))
        self._icon.setToolTip("DBX Stats")
        self._icon.setContextMenu(self._build_menu())
        self._icon.activated.connect(self._on_activated)
        self._icon.show()

    def _build_menu(self) -> QMenu:
        menu = QMenu()
        menu.addAction("Mostrar / ocultar janela", self._ctl.toggle_window)
        views = menu.addMenu("Abrir tela")
        for key, text in _VIEWS:
            views.addAction(text, lambda k=key: self._ctl.show_view(k))
        menu.addSeparator()
        self._overlay_action = QAction("Overlay no jogo", menu, checkable=True)
        self._overlay_action.setChecked(self._ctl.settings.overlay_enabled)
        self._overlay_action.triggered.connect(lambda _v: self._ctl.toggle_overlay())
        menu.addAction(self._overlay_action)
        menu.addAction("Benchmark rápido (60 s)", lambda: self._ctl.benchmark_start(60))
        menu.addAction("Zerar estatísticas", self._ctl.clear_stats)
        menu.addAction("Reiniciar captura de FPS", self._ctl.restart_capture)
        menu.addSeparator()
        menu.addAction("Configurações", lambda: self._ctl.open_settings())
        menu.addAction("Fechar", self._ctl.quit)
        return menu

    def _on_activated(self, reason) -> None:
        if reason in (QSystemTrayIcon.ActivationReason.Trigger,
                      QSystemTrayIcon.ActivationReason.DoubleClick):
            self._ctl.toggle_window()

    def sync(self) -> None:
        self._icon.setIcon(make_icon(self._ctl.settings.accent))
        self._overlay_action.setChecked(self._ctl.settings.overlay_enabled)

    def set_tooltip(self, text: str) -> None:
        self._icon.setToolTip(text)

    def notify(self, title: str, message: str) -> None:
        try:
            self._icon.showMessage(title, message, make_icon(self._ctl.settings.accent))
        except Exception:
            pass

    def hide(self) -> None:
        self._icon.hide()

