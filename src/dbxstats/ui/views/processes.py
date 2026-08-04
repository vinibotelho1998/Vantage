"""Tela de processos: quem esta consumindo CPU e memoria agora."""
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
from ..components import Card, KpiStrip, PillButton
from .base import View

_HEADERS = ["Processo", "PID", "CPU", "Memória", "Threads"]
_KPIS = [
    ("procs", "Processos", ""), ("threads", "Threads", ""), ("cpu", "CPU total", "%"),
    ("ram", "RAM usada", "GB"), ("top", "Maior consumidor", ""),
]


class ProcessesView(View):
    key = "processes"
    title = "Processos"
    glyph = "☰"

    def __init__(self, app) -> None:
        super().__init__(app)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(theme.scaled(theme.GAP))

        self.kpi = KpiStrip(_KPIS, columns=5)
        root.addWidget(self.kpi)

        bar = QHBoxLayout()
        bar.setSpacing(theme.scaled(8))
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("Filtrar por nome…")
        self.filter.setMaximumWidth(theme.scaled(300))
        bar.addWidget(self.filter)
        self.sort_btn = PillButton("Ordenar por CPU", theme.accent_color(self.cfg.accent))
        self.sort_btn.clicked.connect(self._toggle_sort)
        bar.addWidget(self.sort_btn)
        bar.addStretch(1)
        root.addLayout(bar)

        card = Card("Em execução", theme.RAM, "atualiza a cada 2,5 s")
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
        for i, width in ((1, 80), (2, 100), (3, 120), (4, 90)):
            header.setSectionResizeMode(i, QHeaderView.ResizeMode.Fixed)
            self.table.setColumnWidth(i, theme.scaled(width))
            self.table.horizontalHeaderItem(i).setTextAlignment(
                int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter))
        card.add(self.table, 1)
        root.addWidget(card, 1)

        self._sort_ram = False

    def _toggle_sort(self) -> None:
        self._sort_ram = not self._sort_ram
        self.sort_btn.setText("Ordenar por RAM" if self._sort_ram else "Ordenar por CPU")

    def on_settings_changed(self) -> None:
        self.sort_btn.set_color(theme.accent_color(self.cfg.accent))

    def on_system(self, d: dict) -> None:
        rows = self.app.procs.snapshot()
        needle = self.filter.text().strip().lower()
        if needle:
            rows = [p for p in rows if needle in p.name.lower()]
        rows = sorted(rows, key=lambda p: -(p.ram_mb if self._sort_ram else p.cpu))

        count, threads = self.app.procs.totals()
        self.kpi.set("procs", str(count or (d or {}).get("processes", 0)), theme.TXT)
        self.kpi.set("threads", str(threads), theme.TXT)
        self.kpi.set("cpu", f"{(d or {}).get('cpu_pct', 0):.0f}",
                     theme.load_color((d or {}).get("cpu_pct")))
        self.kpi.set("ram", f"{(d or {}).get('ram_used', 0):.1f}", theme.RAM,
                     f"de {(d or {}).get('ram_total', 0):.0f} GB")
        if rows:
            top = rows[0]
            self.kpi.set("top", top.name[:12], theme.WARN,
                         f"{top.cpu:.1f}% · {top.ram_mb:.0f} MB")

        self.table.setUpdatesEnabled(False)
        if self.table.rowCount() != len(rows):
            self.table.setRowCount(len(rows))
            for r in range(len(rows)):
                for c in range(len(_HEADERS)):
                    if self.table.item(r, c) is None:
                        item = QTableWidgetItem("")
                        if c:
                            item.setTextAlignment(int(Qt.AlignmentFlag.AlignRight
                                                      | Qt.AlignmentFlag.AlignVCenter))
                        self.table.setItem(r, c, item)
                self.table.setRowHeight(r, theme.scaled(22))
        for r, p in enumerate(rows):
            name = self.table.item(r, 0)
            name.setText(("🎮  " if p.is_game else "") + p.name)
            name.setForeground(QBrush(QColor(theme.FPS if p.is_game else theme.TXT)))
            name.setFont(QFont(theme.FONT_UI, max(7, theme.scaled(8.5)),
                               QFont.Weight.DemiBold if p.is_game else QFont.Weight.Normal))
            self.table.item(r, 1).setText(str(p.pid))
            cpu = self.table.item(r, 2)
            cpu.setText(f"{p.cpu:.1f}%")
            cpu.setForeground(QBrush(QColor(theme.load_color(p.cpu * 4))))
            self.table.item(r, 3).setText(units.size(p.ram_mb * 1024 ** 2))
            self.table.item(r, 4).setText(str(p.threads))
        self.table.setUpdatesEnabled(True)
