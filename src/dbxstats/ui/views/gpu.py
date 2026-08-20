"""Tela da GPU: uso, VRAM, clocks, potencia, PCIe e motivos de throttle."""
from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout

from ... import theme
from ...core import units
from ..charts import BarMeter, Plot, TimeSeriesChart
from ..components import Badge, Card, KpiStrip, MetricList, label
from .base import View, scroll_page

_KPIS = [
    ("usage", "Uso", "%"), ("temp", "Núcleo", "°C"), ("hotspot", "Hot spot", "°C"),
    ("clock", "Clock", "MHz"), ("power", "Potência", "W"), ("vram", "VRAM", "%"),
    ("fan", "Ventoinha", "%"),
]


class GpuView(View):
    key = "gpu"
    title = "GPU"
    glyph = "▣"

    def __init__(self, app) -> None:
        super().__init__(app)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(theme.scaled(theme.GAP))

        self.kpi = KpiStrip(_KPIS, columns=7)
        root.addWidget(self.kpi)

        page, lay = scroll_page()
        root.addWidget(page, 1)

        card_main = Card("Carga", theme.GPU)
        self.chart = TimeSeriesChart([
            Plot("usage", "Núcleo %", theme.GPU),
            Plot("vram", "VRAM %", theme.RAM, width=1.5),
            Plot("temp", "Temp °C", theme.WARN, width=1.4),
        ], y_max=100.0, height=200)
        card_main.add(self.chart, 1)
        lay.addWidget(card_main, 3)

        row = QHBoxLayout()
        row.setSpacing(theme.scaled(theme.GAP))
        card_clock = Card("Frequência do núcleo", theme.GPU, "MHz")
        self.clock_chart = TimeSeriesChart([
            Plot("core", "Núcleo", theme.GPU, unit=" MHz"),
        ], y_max=None, height=155, unit="")
        card_clock.add(self.clock_chart, 1)
        row.addWidget(card_clock, 1)

        card_power = Card("Potência", theme.DISK, "W")
        self.power_chart = TimeSeriesChart([Plot("watts", "Consumo", theme.DISK, unit=" W")],
                                           y_max=None, height=155, unit="")
        card_power.add(self.power_chart, 1)
        row.addWidget(card_power, 1)
        lay.addLayout(row, 2)

        bottom = QHBoxLayout()
        bottom.setSpacing(theme.scaled(theme.GAP))

        card_vram = Card("Memória de vídeo", theme.RAM)
        self.vram_label = label("—", 20, family=theme.FONT_DISPLAY)
        card_vram.add(self.vram_label)
        self.vram_bar = BarMeter(theme.RAM, 8)
        card_vram.add(self.vram_bar)
        self.vram_rows = MetricList([
            ("used", "Em uso"), ("free", "Livre"), ("ctrl", "Controlador"),
            ("temp", "Temp VRAM"), ("clock", "Clock"),
        ])
        # A faixa geral do app comeca a avisar em 65 graus, e GDDR parada vive
        # nos 68: sem a faixa propria a linha nasceria laranja numa placa sadia.
        self.vram_rows.row("temp").setToolTip(
            "GDDR trabalha quente. Aviso a partir de 95 °C, crítico em 105 °C.")
        card_vram.add(self.vram_rows)
        card_vram.body.addStretch(1)
        bottom.addWidget(card_vram, 1)

        card_info = Card("Adaptador", theme.GPU)
        self.info = MetricList([
            ("name", "Modelo"), ("driver", "Driver"), ("vbios", "VBIOS"),
            ("mode", "Modo de vídeo"), ("pcie", "PCIe"), ("volts", "Tensão do núcleo"),
            ("limit", "Limite de potência"), ("slowdown", "Limite térmico"),
            ("engine", "Encoder / Decoder"), ("pcie_io", "Tráfego PCIe"),
        ])
        card_info.add(self.info)
        card_info.body.addStretch(1)
        bottom.addWidget(card_info, 1)

        card_thr = Card("Estado", theme.WARN, "motivos de limitação relatados pelo driver")
        self.throttle_box = QVBoxLayout()
        self.throttle_box.setSpacing(theme.scaled(5))
        card_thr.add_layout(self.throttle_box)
        self.throttle_badges: list[Badge] = []
        for _ in range(6):
            b = Badge("", theme.FAINT)
            b.setVisible(False)
            self.throttle_box.addWidget(b)
            self.throttle_badges.append(b)
        self.stats_rows = MetricList([
            ("usage", "Uso"), ("temp", "Temperatura"), ("power", "Potência"),
        ])
        card_thr.add(self.stats_rows)
        card_thr.body.addStretch(1)
        bottom.addWidget(card_thr, 1)
        lay.addLayout(bottom, 2)
        lay.addStretch(0)

    def on_settings_changed(self) -> None:
        for chart in (self.chart, self.clock_chart, self.power_chart):
            chart.configure(**self.chart_config())
            chart.set_span(self.cfg.history_window)

    def on_system(self, d: dict) -> None:
        g = (d or {}).get("gpu")
        if not g:
            self.kpi.set("usage", units.DASH, theme.MUTE, "GPU não detectada")
            return
        h = self.history
        usage = g.get("usage")
        temp = g.get("temp")
        watts = g.get("watts")
        vram_pct = g.get("vram_pct")

        self.kpi.set("usage", units.integer(usage), theme.load_color(usage),
                     self.app.stats.fmt("gpu_pct", 0, "%"))
        self.kpi.set("temp", units.integer(temp), theme.temp_color(temp),
                     self.app.stats.fmt("gpu_temp", 0, "°"))
        hot = g.get("temp_hotspot")
        self.kpi.set("hotspot", units.integer(hot), theme.temp_color(hot),
                     "sensor mais quente do die")
        self.kpi.set("clock", units.integer(g.get("freq")), theme.TXT,
                     f"memória {units.mhz(g.get('mem_freq'))}")
        limit = g.get("power_limit")
        self.kpi.set("power", f"{watts:.0f}" if watts is not None else units.DASH,
                     theme.watt_color(watts, (limit or 200) * 0.75, (limit or 200) * 0.95),
                     f"limite {units.watts(limit, 0)}" if limit else "")
        self.kpi.set("vram", units.integer(vram_pct), theme.load_color(vram_pct),
                     units.mib_pair(g.get("vram_used"), g.get("vram_total")))
        fan = g.get("fan_pct")
        self.kpi.set("fan", units.integer(fan), theme.TXT, units.rpm(g.get("fan_rpm")))

        self.chart.set_values("usage", h.values("gpu_pct"))
        self.chart.set_values("vram", h.values("vram_pct"))
        self.chart.set_values("temp", h.values("gpu_temp"))
        self.chart.refresh()
        self.clock_chart.set_values("core", h.values("gpu_mhz"))
        self.clock_chart.refresh()
        self.power_chart.set_values("watts", h.values("gpu_watts"))
        self.power_chart.refresh()

        used, total = g.get("vram_used", 0), max(1, g.get("vram_total", 1))
        self.vram_label.setText(f"{used / 1024:.1f} / {total / 1024:.1f} GB")
        self.vram_label.setStyleSheet(f"color: {theme.load_color(vram_pct)};")
        self.vram_bar.set_value(vram_pct, theme.load_color(vram_pct))
        self.vram_rows.set("used", f"{used} MB")
        self.vram_rows.set("free", f"{total - used} MB")
        self.vram_rows.set("ctrl", units.percent(g.get("mem_ctrl")))
        # Linha some sem sensor: nesta maquina AMD nao ha NVML, e a temperatura da
        # VRAM so' existe em parte das placas. Travessao fixo faz parecer defeito.
        vt = g.get("temp_vram")
        self.vram_rows.row("temp").setVisible(vt is not None)
        self.vram_rows.set("temp", units.temp(vt), theme.vram_temp_color(vt))
        self.vram_rows.set("clock", units.mhz(g.get("mem_freq")))

        static = g.get("static", {})
        self.info.set("name", g.get("name", units.DASH))
        self.info.set("driver", str(static.get("driver", units.DASH)))
        self.info.set("vbios", str(static.get("vbios", units.DASH)))
        mode, refresh = static.get("video_mode"), static.get("refresh")
        self.info.set("mode", f"{mode}  ·  {refresh} Hz" if mode and refresh
                      else (mode or units.DASH))
        gen, width = static.get("pcie_gen"), static.get("pcie_width")
        self.info.set("pcie", f"Gen {gen} x{width}" if gen else units.DASH)
        volts = g.get("volts")
        self.info.row("volts").setVisible(volts is not None)
        self.info.set("volts", f"{volts:.3f} V" if volts is not None else units.DASH)
        self.info.set("limit", units.watts(static.get("power_limit"), 0))
        self.info.set("slowdown", units.temp(static.get("temp_slowdown")))
        self.info.set("engine", f"{units.percent(g.get('encoder'))} / "
                                f"{units.percent(g.get('decoder'))}")
        tx, rx = g.get("pcie_tx"), g.get("pcie_rx")
        self.info.set("pcie_io", f"↑{units.rate((tx or 0) * 1024)}  "
                                 f"↓{units.rate((rx or 0) * 1024)}" if tx is not None
                      else units.DASH)

        reasons = [r for r in (g.get("throttle") or []) if r != "Display ativo"]
        if reasons:
            color = theme.WARN
        elif g.get("throttle_supported"):
            reasons = ["Sem limitação ativa"]
            color = theme.OK
        else:
            reasons = ["Driver não reporta limitação"]
            color = theme.MUTE
        for i, badge in enumerate(self.throttle_badges):
            if i < len(reasons):
                badge.update_badge(reasons[i], color)
                badge.setVisible(True)
            else:
                badge.setVisible(False)

        st = self.app.stats
        self.stats_rows.set("usage", st.fmt("gpu_pct", 0, "%") or units.DASH)
        self.stats_rows.set("temp", st.fmt("gpu_temp", 0, "°C") or units.DASH)
        self.stats_rows.set("power", st.fmt("gpu_watts", 0, " W") or units.DASH)
