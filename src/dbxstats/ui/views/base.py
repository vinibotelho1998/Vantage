"""Contrato comum das telas.

O controlador chama `on_system` na cadencia do coletor e `on_fps` na cadencia
rapida; e apenas para a view visivel, entao telas ocultas custam zero CPU.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QScrollArea, QVBoxLayout, QWidget

from ... import theme


class View(QWidget):
    key: str = ""
    title: str = ""
    glyph: str = "•"
    subtitle: str = ""

    def __init__(self, app) -> None:
        super().__init__()
        self.app = app
        self.setObjectName("ViewRoot")

    def on_system(self, data: dict) -> None:
        """Novo snapshot do coletor."""

    def on_fps(self) -> None:
        """Tick rapido (FPS / frametime)."""

    def on_settings_changed(self) -> None:
        """Configuracoes mudaram (acento, suavizacao, janelas)."""

    def on_activate(self) -> None:
        """A view acabou de virar a visivel."""

    @property
    def cfg(self):
        return self.app.settings

    @property
    def history(self):
        return self.app.history

    def chart_config(self) -> dict:
        c = self.cfg
        return {"smooth": c.smooth_lines, "fill": c.fill_area,
                "grid": c.show_grid, "glow": c.chart_glow}


def scroll_page(spacing: int | None = None) -> tuple[QScrollArea, QVBoxLayout]:
    """Cria uma area rolavel com layout vertical pronto para receber cards."""
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setFrameShape(QScrollArea.Shape.NoFrame)
    area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    page = QWidget()
    page.setObjectName("Content")
    lay = QVBoxLayout(page)
    lay.setContentsMargins(0, 0, theme.scaled(6), theme.scaled(4))
    lay.setSpacing(theme.scaled(spacing if spacing is not None else theme.GAP))
    area.setWidget(page)
    return area, lay
