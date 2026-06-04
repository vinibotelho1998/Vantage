"""Icone na bandeja do sistema com menu de acoes."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from .. import theme


def make_icon(accent: str) -> QIcon:
    px = QPixmap(64, 64)
    px.fill(Qt.GlobalColor.transparent)
    p = QPainter(px)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(theme.BG))
    p.drawRoundedRect(3, 3, 58, 58, 14, 14)
    base = 50
    bars = [(13, 22, theme.CPU), (25, 34, theme.RAM),
            (37, 16, theme.GPU), (49, 28, theme.accent_color(accent))]
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
        menu = QMenu()
        menu.addAction("Mostrar / ocultar painel", controller.toggle_panel)
        menu.addAction("Modo Jogo (overlay)", controller.toggle_overlay)
        menu.addAction("Configurações", lambda: controller.open_settings(0))
        menu.addSeparator()
        menu.addAction("Fechar", controller.quit)
        self._icon.setContextMenu(menu)
        self._icon.activated.connect(self._on_activated)
        self._icon.show()

    def _on_activated(self, reason) -> None:
        if reason in (QSystemTrayIcon.ActivationReason.Trigger,
                      QSystemTrayIcon.ActivationReason.DoubleClick):
            self._ctl.toggle_panel()

    def update_icon(self, accent: str) -> None:
        self._icon.setIcon(make_icon(accent))

    def hide(self) -> None:
        self._icon.hide()
