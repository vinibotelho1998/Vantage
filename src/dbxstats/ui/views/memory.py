"""Tela de memoria e armazenamento: RAM, swap, unidades, temperatura e I/O."""
from __future__ import annotations

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QVBoxLayout

from ... import theme
from ...core import units
from ..charts import BarMeter, Plot, Sparkline, TimeSeriesChart
from ..components import Card, KpiStrip, MetricList, label
from .base import View, scroll_page

_KPIS = [
    ("used", "Em uso", "GB"), ("pct", "Ocupação", "%"), ("avail", "Disponível", "GB"),
    ("freq", "Frequência", "MHz"), ("swap", "Swap", "GB"), ("disk", "Disco do sistema", "%"),
]


class MemoryView(View):
    key = "memory"
    title = "Memória & Disco"
    glyph = "▤"

    def __init__(self, app) -> None:
        super().__init__(app)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(theme.scaled(theme.GAP))

        self.kpi = KpiStrip(_KPIS, columns=6)
        root.addWidget(self.kpi)

        page, lay = scroll_page()
        root.addWidget(page, 1)

        row = QHBoxLayout()
        row.setSpacing(theme.scaled(theme.GAP))
        card_ram = Card("Memória do sistema", theme.RAM)
        self.ram_chart = TimeSeriesChart([
            Plot("ram", "RAM %", theme.RAM),
            Plot("swap", "Swap %", theme.FAINT, width=1.4, dashed=True),
        ], y_max=100.0, height=175)
        card_ram.add(self.ram_chart, 1)
        self.ram_rows = MetricList([
            ("total", "Total"), ("used", "Em uso"), ("cached", "Cache do sistema"),
            ("avail", "Disponível"), ("swap", "Arquivo de paginação"),
            ("modules", "Módulos"),
        ])
        card_ram.add(self.ram_rows)
        row.addWidget(card_ram, 1)

        card_io = Card("Atividade de disco", theme.DISK)
        self.io_chart = TimeSeriesChart([
            Plot("read", "Leitura", theme.GPU, unit=" MB/s"),
            Plot("write", "Escrita", theme.DISK, unit=" MB/s"),
        ], y_max=None, height=175, unit="")
        card_io.add(self.io_chart, 1)
        self.io_rows = MetricList([
            ("read", "Leitura"), ("write", "Escrita"), ("total", "Total agora"),
            ("temp", "Temperatura NVMe"), ("drives", "Unidades"), ("uptime", "Ligado há"),
        ])
        card_io.add(self.io_rows)
        row.addWidget(card_io, 1)
        lay.addLayout(row, 3)

        card_drives = Card("Unidades", theme.DISK)
        self.drive_grid = QGridLayout()
        self.drive_grid.setSpacing(theme.scaled(theme.GAP))
        card_drives.add_layout(self.drive_grid)
        self._drive_widgets: list[dict] = []
        lay.addWidget(card_drives, 2)
        lay.addStretch(0)

    def on_settings_changed(self) -> None:
        for chart in (self.ram_chart, self.io_chart):
            chart.configure(**self.chart_config())
            chart.set_span(self.cfg.history_window)

    def on_system(self, d: dict) -> None:
        if not d:
            return
        h = self.history
        pct = d.get("ram_pct")
        self.kpi.set("used", f"{d.get('ram_used', 0):.1f}", theme.RAM,
                     f"de {d.get('ram_total', 0):.0f} GB")
        self.kpi.set("pct", units.integer(pct), theme.load_color(pct),
                     self.app.stats.fmt("ram_pct", 0, "%"))
        self.kpi.set("avail", f"{d.get('ram_avail', 0):.1f}", theme.TXT)
        info = d.get("ram_info") or {}
        self.kpi.set("freq", units.integer(d.get("ram_freq")), theme.TXT,
                     info.get("type", ""))
        self.kpi.set("swap", f"{d.get('swap_used', 0):.1f}", theme.TXT,
                     f"de {d.get('swap_total', 0):.0f} GB")
        dp = d.get("disk_pct")
        self.kpi.set("disk", units.integer(dp), theme.load_color(dp),
                     f"{d.get('disk_used', 0):.0f} / {d.get('disk_total', 0):.0f} GB")

        self.ram_chart.set_values("ram", h.values("ram_pct"))
        self.ram_chart.set_values("swap", h.values("swap_pct"))
        self.ram_chart.refresh()
        self.io_chart.set_values("read", [v / 1024 ** 2 for v in h.values("disk_r")])
        self.io_chart.set_values("write", [v / 1024 ** 2 for v in h.values("disk_w")])
        self.io_chart.refresh()

        self.ram_rows.set("total", units.gib(d.get("ram_total"), 0))
        self.ram_rows.set("used", units.gib(d.get("ram_used")), theme.load_color(pct))
        self.ram_rows.set("cached", units.gib(d.get("ram_cached")))
        self.ram_rows.set("avail", units.gib(d.get("ram_avail")))
        self.ram_rows.set("swap", f"{d.get('swap_used', 0):.1f} / "
                                  f"{d.get('swap_total', 0):.0f} GB")
        self.ram_rows.set("modules", f"{info.get('modules', '?')}× {info.get('part', '')}".strip()
                          if info else units.DASH)

        self.io_rows.set("read", units.rate(d.get("disk_r")))
        self.io_rows.set("write", units.rate(d.get("disk_w")))
        self.io_rows.set("total", units.rate((d.get("disk_r") or 0) + (d.get("disk_w") or 0)))
        nt = d.get("nvme_temp")
        self.io_rows.set("temp", units.temp(nt), theme.temp_color(nt))
        drives = d.get("disks") or []
        self.io_rows.set("drives", str(len(drives)))
        self.io_rows.set("uptime", units.duration(d.get("uptime")))

        self._sync_drives(drives)

    def _sync_drives(self, drives: list[dict]) -> None:
        while len(self._drive_widgets) < len(drives):
            i = len(self._drive_widgets)
            box = QVBoxLayout()
            box.setSpacing(theme.scaled(4))
            title = label("", 10, QFont.Weight.DemiBold, theme.TXT)
            sub = label("", 7.5, QFont.Weight.Normal, theme.FAINT)
            bar = BarMeter(theme.DISK, 7)
            detail = label("", 8, QFont.Weight.Normal, theme.MUTE)
            spark = Sparkline(theme.DISK, 26)
            for w in (title, sub, bar, detail, spark):
                box.addWidget(w)
            self.drive_grid.addLayout(box, i // 4, i % 4)
            self.drive_grid.setColumnStretch(i % 4, 1)
            self._drive_widgets.append({"title": title, "sub": sub, "bar": bar,
                                        "detail": detail, "spark": spark})
        for i, w in enumerate(self._drive_widgets):
            visible = i < len(drives)
            for widget in w.values():
                widget.setVisible(visible)
            if not visible:
                continue
            drive = drives[i]
            pct = drive.get("pct", 0.0)
            w["title"].setText(f"{drive.get('mount', '?')}  ·  {drive.get('fstype', '')}")
            w["sub"].setText(drive.get("model") or drive.get("device", ""))
            w["bar"].set_value(pct, theme.load_color(pct))
            temp = drive.get("temp")
            life = drive.get("life")
            extra = f"  ·  {units.temp(temp)}" if temp else ""
            extra += f"  ·  vida {life:.0f}%" if life else ""
            w["detail"].setText(
                f"{drive.get('used', 0):.0f} / {drive.get('total', 0):.0f} GB"
                f"  ({pct:.0f}%){extra}")
            w["spark"].setVisible(False)
