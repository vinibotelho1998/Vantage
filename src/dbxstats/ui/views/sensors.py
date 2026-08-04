"""Tela de sensores: arvore completa do LibreHardwareMonitor com mín/méd/máx."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLineEdit,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from ... import theme
from ...core import units
from ..components import Badge, Card, PillButton, label
from .base import View

_HEADERS = ["Sensor", "Atual", "Mínimo", "Médio", "Máximo"]
_KIND_COLORS = {
    "Temperature": theme.WARN, "Power": theme.DISK, "Load": theme.CPU,
    "Clock": theme.FPS, "Fan": theme.GPU, "Voltage": theme.RAM,
    "Control": theme.GPU, "Data": theme.MUTE, "SmallData": theme.MUTE,
    "Throughput": theme.NET, "Level": theme.RAM,
}


class SensorsView(View):
    key = "sensors"
    title = "Sensores"
    glyph = "◈"

    def __init__(self, app) -> None:
        super().__init__(app)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(theme.scaled(theme.GAP))

        bar = QHBoxLayout()
        bar.setSpacing(theme.scaled(8))
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("Filtrar sensores (ex.: temp, fan, core)…")
        self.filter.setMaximumWidth(theme.scaled(320))
        self.filter.textChanged.connect(self._rebuild_soon)
        bar.addWidget(self.filter)
        self.reset_btn = PillButton("Zerar mín/máx", theme.MUTE)
        self.reset_btn.clicked.connect(self.app.clear_stats)
        bar.addWidget(self.reset_btn)
        self.export_btn = PillButton("Exportar CSV", theme.accent_color(self.cfg.accent))
        self.export_btn.clicked.connect(self._export)
        bar.addWidget(self.export_btn)
        bar.addStretch(1)
        self.count_badge = Badge("0 sensores", theme.FAINT)
        bar.addWidget(self.count_badge)
        root.addLayout(bar)

        card = Card("Todos os sensores", theme.accent_color(self.cfg.accent),
                    "leitura direta do LibreHardwareMonitor")
        self.table = QTableWidget(0, len(_HEADERS))
        self.table.setHorizontalHeaderLabels(_HEADERS)
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        header = self.table.horizontalHeader()
        header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for i in range(1, len(_HEADERS)):
            header.setSectionResizeMode(i, QHeaderView.ResizeMode.Fixed)
            self.table.setColumnWidth(i, theme.scaled(110))
            self.table.horizontalHeaderItem(i).setTextAlignment(
                int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter))
        card.add(self.table, 1)
        root.addWidget(card, 1)

        self.empty = label("Aguardando o LibreHardwareMonitor…", 9,
                           QFont.Weight.Normal, theme.FAINT)
        root.addWidget(self.empty)

        self._keys: list[str] = []
        self._rows: dict[str, int] = {}
        self._dirty = True

    def _rebuild_soon(self) -> None:
        self._dirty = True

    def on_activate(self) -> None:
        self._dirty = True

    def on_settings_changed(self) -> None:
        self.export_btn.set_color(theme.accent_color(self.cfg.accent))

    def on_system(self, _d: dict) -> None:
        nodes = self.app.lhm.tree()
        if not nodes:
            self.empty.setVisible(True)
            return
        self.empty.setVisible(False)
        needle = self.filter.text().strip().lower()
        if needle:
            nodes = [n for n in nodes
                     if needle in n.name.lower() or needle in n.hardware.lower()
                     or needle in n.kind.lower()]
        keys = [n.key for n in nodes]
        if self._dirty or keys != self._keys:
            self._build_table(nodes)
            self._keys = keys
            self._dirty = False
        self._update_values(nodes)
        self.count_badge.update_badge(f"{len(nodes)} sensores", theme.MUTE)

    def _build_table(self, nodes) -> None:
        self.table.setUpdatesEnabled(False)
        self.table.setRowCount(0)
        self._rows = {}
        current_hw = None
        row = 0
        for node in nodes:
            if node.hardware != current_hw:
                current_hw = node.hardware
                self.table.insertRow(row)
                item = QTableWidgetItem(current_hw)
                item.setFont(QFont(theme.FONT_UI, max(7, theme.scaled(9)), QFont.Weight.Bold))
                item.setForeground(QBrush(QColor(theme.accent_color(self.cfg.accent))))
                self.table.setItem(row, 0, item)
                for c in range(1, len(_HEADERS)):
                    self.table.setItem(row, c, QTableWidgetItem(""))
                self.table.setRowHeight(row, theme.scaled(26))
                row += 1
            self.table.insertRow(row)
            name = QTableWidgetItem(f"    {node.name}")
            name.setForeground(QBrush(QColor(theme.MUTE)))
            self.table.setItem(row, 0, name)
            for c in range(1, len(_HEADERS)):
                cell = QTableWidgetItem("—")
                cell.setTextAlignment(int(Qt.AlignmentFlag.AlignRight
                                          | Qt.AlignmentFlag.AlignVCenter))
                cell.setForeground(QBrush(QColor(theme.FAINT if c > 1 else theme.TXT)))
                self.table.setItem(row, c, cell)
            self.table.setRowHeight(row, theme.scaled(22))
            self._rows[node.key] = row
            row += 1
        self.table.setUpdatesEnabled(True)

    def _update_values(self, nodes) -> None:
        stats = self.app.stats
        for node in nodes:
            row = self._rows.get(node.key)
            if row is None:
                continue
            color = _KIND_COLORS.get(node.kind, theme.TXT)
            if node.kind == "Temperature":
                color = theme.temp_color(node.value)
            elif node.kind in ("Load", "Control", "Level"):
                color = theme.load_color(node.value)
            cur = self.table.item(row, 1)
            cur.setText(units.sensor_value(node.value, node.unit))
            cur.setForeground(QBrush(QColor(color)))
            agg = stats.get(node.key)
            if agg is None:
                continue
            mn, av, mx = agg
            for col, value in ((2, mn), (3, av), (4, mx)):
                self.table.item(row, col).setText(units.sensor_value(value, node.unit))

    def _export(self) -> None:
        from ...core.export import export_sensors
        path = export_sensors(self.app.lhm.tree(), self.app.stats)
        if path:
            self.app.notify("DBX Stats", f"Sensores exportados para {path.name}")
