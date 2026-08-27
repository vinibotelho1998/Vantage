"""Blocos reutilizaveis da interface: cards, tiles, linhas de metrica e navegacao."""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .. import theme
from ..core import units


def font(pt: float, weight: int = QFont.Weight.Normal, family: str = theme.FONT_UI) -> QFont:
    f = QFont(family)
    f.setPointSizeF(max(5.5, pt * theme.SCALE))
    f.setWeight(weight)
    return f


def label(text: str = "", pt: float = 9, weight: int = QFont.Weight.Normal,
          color: str | None = None, family: str = theme.FONT_UI,
          align: Qt.AlignmentFlag | None = None) -> QLabel:
    lb = QLabel(text)
    lb.setFont(font(pt, weight, family))
    if color:
        lb.setStyleSheet(f"color: {color}; background: transparent;")
    if align is not None:
        lb.setAlignment(align)
    return lb


def dimm_color(snapshot: dict) -> str:
    """Cor da temperatura da RAM na faixa que o proprio pente publica.

    Os limites vem de fabrica no SPD (High Limit e Critical High) e mudam de
    modulo para modulo. Usar a escala geral do app aqui erra nas duas pontas: 55
    graus num pente ja' e' aviso do fabricante e no processador seria ociosidade.
    Sem modulo nenhum a funcao cai nos valores tipicos de DDR5.
    """
    modulos = [m for m in (snapshot.get("ram_modules") or []) if isinstance(m, dict)]
    alto = min((m["high"] for m in modulos if m.get("high")), default=None)
    critico = min((m["critical"] for m in modulos if m.get("critical")), default=None)
    return theme.dimm_temp_color(snapshot.get("ram_temp"), alto, critico)


def linha_opcional(lista, chave: str, valor, texto, cor) -> None:
    """Preenche uma linha de MetricList, ou faz a linha sumir se nao ha' leitura.

    Travessao fixo numa linha diz "isto quebrou"; linha ausente diz "esta maquina
    nao mede isso", que e' a verdade quando falta o sensor, e e' o que mantem o
    card honesto numa maquina sem NVML, sem sensor de pente ou sem elevacao.
    """
    row = lista.row(chave)
    if row is None:
        return
    row.setVisible(valor is not None)
    if valor is not None:
        row.set(texto(valor), cor(valor) if callable(cor) else cor)


def divider(vertical: bool = False) -> QFrame:
    f = QFrame()
    f.setObjectName("Divider")
    if vertical:
        f.setFixedWidth(1)
        f.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
    else:
        f.setFixedHeight(1)
        f.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    return f


def spacer(width: int = 0, height: int = 0) -> QWidget:
    w = QWidget()
    w.setFixedSize(theme.scaled(width) if width else 0, theme.scaled(height) if height else 0)
    return w


class Badge(QLabel):
    """Pilula compacta para estados (VSync, gargalo, alertas)."""

    def __init__(self, text: str = "", color: str = theme.MUTE,
                 parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setFont(font(7.5, QFont.Weight.Bold))
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self.set_color(color)

    def set_color(self, color: str) -> None:
        self._color = color
        self.setStyleSheet(
            f"color: {color}; background: {theme.rgba(color, 0.13)};"
            f" border: 1px solid {theme.rgba(color, 0.35)};"
            f" border-radius: {theme.scaled(9)}px; padding: {theme.scaled(2)}px"
            f" {theme.scaled(9)}px;")

    def update_badge(self, text: str, color: str) -> None:
        self.setText(text)
        if color != getattr(self, "_color", None):
            self.set_color(color)


class Card(QFrame):
    """Container padrao: titulo, marcador colorido, dica a direita e corpo livre."""

    def __init__(self, title: str = "", color: str = theme.CPU, hint: str = "",
                 compact: bool = False, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Card")
        self._color = color
        pad = theme.scaled(10 if compact else theme.PAD)
        root = QVBoxLayout(self)
        root.setContentsMargins(pad, theme.scaled(9 if compact else 11), pad,
                                theme.scaled(9 if compact else 12))
        root.setSpacing(theme.scaled(7))

        self.header = QHBoxLayout()
        self.header.setSpacing(theme.scaled(8))
        self._tick = QFrame()
        self._tick.setFixedSize(theme.scaled(3), theme.scaled(13))
        self._tick.setStyleSheet(f"background: {color}; border-radius: 1px;")
        self._title = label(title.upper(), 8, QFont.Weight.Bold, theme.MUTE)
        self._title.setStyleSheet(
            f"color: {theme.MUTE}; letter-spacing: 1.1px; background: transparent;")
        self._hint = label(hint, 8, QFont.Weight.Normal, theme.FAINT)
        self._hint.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.header.addWidget(self._tick)
        self.header.addWidget(self._title)
        self.header.addStretch(1)
        self.header.addWidget(self._hint)
        if title:
            root.addLayout(self.header)

        self.body = QVBoxLayout()
        self.body.setContentsMargins(0, 0, 0, 0)
        self.body.setSpacing(theme.scaled(7))
        root.addLayout(self.body, 1)
        self._root = root

    def set_hint(self, text: str, color: str | None = None) -> None:
        self._hint.setText(text)
        if color:
            self._hint.setStyleSheet(f"color: {color}; background: transparent;")

    def set_title(self, text: str) -> None:
        self._title.setText(text.upper())

    def add_header_widget(self, widget: QWidget) -> None:
        self.header.addWidget(widget)

    def add(self, widget: QWidget, stretch: int = 0) -> QWidget:
        self.body.addWidget(widget, stretch)
        return widget

    def add_layout(self, layout, stretch: int = 0):
        self.body.addLayout(layout, stretch)
        return layout


class StatTile(QFrame):
    """Numero grande com legenda, usado nas faixas de KPI."""

    def __init__(self, caption: str, unit: str = "", color: str = theme.TXT,
                 big: float = 22, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Tile")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(theme.scaled(12), theme.scaled(8), theme.scaled(12),
                               theme.scaled(9))
        lay.setSpacing(0)
        self._caption = label(caption.upper(), 7.5, QFont.Weight.Bold, theme.FAINT)
        self._caption.setStyleSheet(
            f"color: {theme.FAINT}; letter-spacing: 1px; background: transparent;")
        row = QHBoxLayout()
        row.setSpacing(theme.scaled(3))
        row.setContentsMargins(0, 0, 0, 0)
        self._value = label("—", big, QFont.Weight.Bold, color, theme.FONT_DISPLAY)
        self._unit = label(unit, 8.5, QFont.Weight.DemiBold, theme.FAINT)
        self._unit.setAlignment(Qt.AlignmentFlag.AlignBottom)
        row.addWidget(self._value)
        row.addWidget(self._unit)
        row.addStretch(1)
        self._sub = label("", 7.5, QFont.Weight.Normal, theme.FAINT)
        lay.addWidget(self._caption)
        lay.addLayout(row)
        lay.addWidget(self._sub)
        self._color = color

    def set(self, value: str, color: str | None = None, sub: str | None = None) -> None:
        self._value.setText(value)
        if color and color != self._color:
            self._color = color
            self._value.setStyleSheet(f"color: {color}; background: transparent;")
        if sub is not None:
            self._sub.setText(sub)

    def set_unit(self, unit: str) -> None:
        self._unit.setText(unit)

    def set_caption(self, text: str) -> None:
        self._caption.setText(text.upper())


class MetricRow(QWidget):
    """Linha rotulo -> valor com estatistica opcional (mín/méd/máx)."""

    def __init__(self, text: str, label_pt: float = 8.5, value_pt: float = 9.5,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, theme.scaled(1), 0, theme.scaled(1))
        lay.setSpacing(0)
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(theme.scaled(8))
        self._label = label(text, label_pt, QFont.Weight.Normal, theme.MUTE)
        self._value = label(units.DASH, value_pt, QFont.Weight.DemiBold, theme.TXT)
        self._value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        top.addWidget(self._label)
        top.addStretch(1)
        top.addWidget(self._value)
        lay.addLayout(top)
        self._stat = label("", 7, QFont.Weight.Normal, theme.FAINT)
        self._stat.setAlignment(Qt.AlignmentFlag.AlignRight)
        self._stat.setVisible(False)
        lay.addWidget(self._stat)
        self._color = theme.TXT

    def set(self, text: str, color: str | None = None) -> None:
        self._value.setText(text)
        target = color or theme.TXT
        if target != self._color:
            self._color = target
            self._value.setStyleSheet(f"color: {target}; background: transparent;")

    def set_stat(self, text: str) -> None:
        self._stat.setText(text)
        self._stat.setVisible(bool(text))

    def set_label(self, text: str) -> None:
        self._label.setText(text)


class MetricList(QWidget):
    """Conjunto de MetricRow indexado por chave."""

    def __init__(self, rows: list[tuple[str, str]], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self._rows: dict[str, MetricRow] = {}
        for key, text in rows:
            row = MetricRow(text)
            self._rows[key] = row
            lay.addWidget(row)

    def set(self, key: str, text: str, color: str | None = None) -> None:
        row = self._rows.get(key)
        if row is not None:
            row.set(text, color)

    def set_stat(self, key: str, text: str) -> None:
        row = self._rows.get(key)
        if row is not None:
            row.set_stat(text)

    def set_label(self, key: str, text: str) -> None:
        row = self._rows.get(key)
        if row is not None:
            row.set_label(text)

    def row(self, key: str) -> MetricRow | None:
        return self._rows.get(key)


_TILE_MIN = 132


class KpiStrip(QWidget):
    """Faixa de StatTile que reflui conforme a largura disponivel.

    O numero de colunas era fixo, entao ao estreitar a janela os tiles eram
    espremidos abaixo da largura minima e o texto vazava por cima do vizinho. Aqui
    as colunas sao recalculadas a cada redimensionamento: cabe menos por linha,
    quebra em mais linhas, e nada se sobrepoe.
    """

    def __init__(self, specs: list[tuple[str, str, str]], columns: int = 6,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setSpacing(theme.scaled(theme.GAP))
        # Sem isso o grid propaga para o widget uma largura minima igual a soma
        # dos tiles, o widget nunca encolhe, o resizeEvent nunca ve largura
        # pequena e a quebra jamais acontece. E' o que fazia a faixa transbordar.
        self._grid.setSizeConstraint(QGridLayout.SizeConstraint.SetNoConstraint)
        self.setMinimumWidth(theme.scaled(_TILE_MIN))
        self._max_columns = max(1, columns)
        self._columns = 0
        self.tiles: dict[str, StatTile] = {}
        self._order: list[tuple[str, StatTile]] = []
        self._ocultos: set[str] = set()
        """Chaves que a maquina nao tem como preencher; ver show_only.

        A lista de escondidos vive aqui, e nao em `isHidden()` de cada tile,
        por causa de um ovo-e-galinha: um widget recem-criado, ainda sem pai,
        responde `isHidden()` verdadeiro. O filtro entao nunca punha nenhum tile
        no grid, e sem entrar no grid ele nunca ganhava pai; a faixa inteira
        ficava vazia em todas as telas que nao chamam show_only.
        """
        for key, caption, unit in specs:
            tile = StatTile(caption, unit)
            tile.setMinimumWidth(theme.scaled(_TILE_MIN))
            self.tiles[key] = tile
            self._order.append((key, tile))
        self._relayout(self._max_columns)

    def _relayout(self, columns: int, forcar: bool = False) -> None:
        if columns == self._columns and not forcar:
            return
        self._columns = columns
        while self._grid.count():
            self._grid.takeAt(0)
        for i in range(self._grid.columnCount()):
            self._grid.setColumnStretch(i, 0)
        visiveis = [t for chave, t in self._order if chave not in self._ocultos]
        for i, tile in enumerate(visiveis):
            self._grid.addWidget(tile, i // columns, i % columns)
        for i in range(min(columns, len(visiveis) or 1)):
            self._grid.setColumnStretch(i, 1)

    def show_only(self, keys) -> None:
        """Esconde os tiles que essa maquina nao tem como preencher.

        Travessao em metade da faixa nao informa nada e ainda faz o app parecer
        quebrado: numa maquina sem sensor de temperatura, ou sem GPU dedicada,
        e' melhor a faixa ficar menor e inteira do que grande e furada.
        """
        ocultos = {chave for chave in self.tiles if chave not in set(keys)}
        if ocultos == self._ocultos:
            return
        self._ocultos = ocultos
        for chave, tile in self.tiles.items():
            tile.setVisible(chave not in ocultos)
        self._relayout(self._columns, forcar=True)

    def resizeEvent(self, event) -> None:
        gap = theme.scaled(theme.GAP)
        largura = max(1, self.width())
        cabem = max(1, (largura + gap) // (theme.scaled(_TILE_MIN) + gap))
        self._relayout(min(self._max_columns, int(cabem), len(self._order) or 1))
        super().resizeEvent(event)

    def set(self, key: str, value: str, color: str | None = None,
            sub: str | None = None) -> None:
        tile = self.tiles.get(key)
        if tile is not None:
            tile.set(value, color, sub)


class NavButton(QFrame):
    """Item da barra lateral."""

    clicked = Signal(str)

    def __init__(self, key: str, text: str, glyph: str,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.key = key
        self.setObjectName("NavButton")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setProperty("active", False)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(theme.scaled(12), theme.scaled(8), theme.scaled(10),
                               theme.scaled(8))
        lay.setSpacing(theme.scaled(10))
        self._glyph = label(glyph, 11, QFont.Weight.Bold, theme.MUTE)
        self._glyph.setFixedWidth(theme.scaled(18))
        self._glyph.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._text = label(text, 9, QFont.Weight.DemiBold, theme.MUTE)
        lay.addWidget(self._glyph)
        lay.addWidget(self._text)
        lay.addStretch(1)
        self._badge = label("", 7.5, QFont.Weight.Bold, theme.FAINT)
        lay.addWidget(self._badge)

    def set_active(self, active: bool, accent: str) -> None:
        self.setProperty("active", active)
        color = accent if active else theme.MUTE
        self._glyph.setStyleSheet(f"color: {color}; background: transparent;")
        self._text.setStyleSheet(
            f"color: {theme.TXT if active else theme.MUTE}; background: transparent;")
        self.style().unpolish(self)
        self.style().polish(self)

    def set_badge(self, text: str, color: str = theme.FAINT) -> None:
        self._badge.setText(text)
        self._badge.setStyleSheet(f"color: {color}; background: transparent;")

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.key)
        event.accept()


class IconButton(QLabel):
    """Botao de texto/glifo usado na barra de titulo."""

    clicked = Signal()

    def __init__(self, glyph: str, tooltip: str = "", danger: bool = False,
                 pt: float = 11, parent: QWidget | None = None) -> None:
        super().__init__(glyph, parent)
        self._danger = danger
        self.setFont(font(pt, QFont.Weight.Bold))
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setFixedSize(theme.scaled(30), theme.scaled(24))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(tooltip)
        self._paint(False)

    def _paint(self, hover: bool) -> None:
        if hover:
            bg = theme.rgba(theme.BAD, 0.85) if self._danger else theme.SURFACE_3
            fg = theme.TXT
        else:
            bg = "transparent"
            fg = theme.MUTE
        self.setStyleSheet(
            f"color: {fg}; background: {bg}; border-radius: {theme.scaled(5)}px;")

    def enterEvent(self, event) -> None:
        self._paint(True)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._paint(False)
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        event.accept()


class PillButton(QLabel):
    """Botao secundario em formato de pilula (usado em barras de acao)."""

    clicked = Signal()

    def __init__(self, text: str, color: str = theme.MUTE, filled: bool = False,
                 parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self._color = color
        self._filled = filled
        self.setFont(font(8.5, QFont.Weight.DemiBold))
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self._apply(False)

    def _apply(self, hover: bool) -> None:
        c = self._color
        if self._filled:
            bg = theme.rgba(c, 0.95 if hover else 0.82)
            fg = theme.BG
        else:
            bg = theme.rgba(c, 0.22 if hover else 0.12)
            fg = c
        self.setStyleSheet(
            f"color: {fg}; background: {bg}; border: 1px solid {theme.rgba(c, 0.32)};"
            f" border-radius: {theme.scaled(13)}px;"
            f" padding: {theme.scaled(5)}px {theme.scaled(14)}px;")

    def set_color(self, color: str) -> None:
        self._color = color
        self._apply(False)

    def enterEvent(self, event) -> None:
        self._apply(True)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._apply(False)
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        event.accept()


class LoadDots(QWidget):
    """Indicador discreto de saude de uma fonte de dados."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._items: list[tuple[str, str]] = []
        self.setFixedHeight(theme.scaled(14))
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_items(self, items: list[tuple[str, str]]) -> None:
        if items != self._items:
            self._items = items
            self.update()

    def sizeHint(self) -> QSize:
        return QSize(theme.scaled(160), theme.scaled(14))

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHints(QPainter.RenderHint.Antialiasing
                         | QPainter.RenderHint.TextAntialiasing)
        p.setFont(font(7, QFont.Weight.DemiBold))
        x = 0.0
        for text, color in self._items:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(color))
            p.drawEllipse(int(x), int(self.height() / 2 - 3), 6, 6)
            p.setPen(QColor(theme.FAINT))
            width = p.fontMetrics().horizontalAdvance(text)
            p.drawText(int(x + 10), int(self.height() / 2 + 4), text)
            x += 10 + width + theme.scaled(12)
