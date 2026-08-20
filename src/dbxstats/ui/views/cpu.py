"""Tela da CPU: uso por nucleo, clocks, temperatura, potencia e processos."""
from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout

from ... import theme
from ...core import units
from ..charts import CoreGrid, Plot, TimeSeriesChart
from ..components import Card, KpiStrip, MetricList
from .base import View, scroll_page

_KPIS = [
    ("usage", "Uso", "%"), ("clock", "Clock", "GHz"), ("temp", "Temperatura", "°C"),
    ("power", "Potência", "W"), ("fan", "Cooler", "RPM"), ("procs", "Processos", ""),
]

_FONTE_VOLTS = {
    "vcore": "rail nomeado pela placa",
    "cpu": "sensor do próprio processador",
    "rail": "rail anônimo, identificado por variação",
}
"""De onde saiu o Vcore. A procedencia importa porque o valor anonimo foi
escolhido por correlacao com a potencia, e nao por nome — em outra placa o mesmo
indice poderia ser outro trilho."""


class CpuView(View):
    key = "cpu"
    title = "CPU"
    glyph = "⚙"

    def __init__(self, app) -> None:
        super().__init__(app)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(theme.scaled(theme.GAP))

        self.kpi = KpiStrip(_KPIS, columns=6)
        root.addWidget(self.kpi)

        page, lay = scroll_page()
        root.addWidget(page, 1)

        card_main = Card("Uso e temperatura", theme.CPU)
        self.chart = TimeSeriesChart([
            Plot("usage", "Uso %", theme.CPU),
            Plot("temp", "Temp °C", theme.WARN, width=1.5),
        ], y_max=100.0, height=190)
        card_main.add(self.chart, 1)
        lay.addWidget(card_main, 3)

        row = QHBoxLayout()
        row.setSpacing(theme.scaled(theme.GAP))
        card_clock = Card("Frequência", theme.CPU, "MHz")
        self.clock_chart = TimeSeriesChart([Plot("clock", "Clock", theme.FPS, unit=" MHz")],
                                           y_max=None, height=150, unit="")
        card_clock.add(self.clock_chart, 1)
        row.addWidget(card_clock, 1)

        card_power = Card("Potência", theme.DISK, "W")
        self.power_chart = TimeSeriesChart([Plot("watts", "Pacote", theme.DISK, unit=" W")],
                                           y_max=None, height=150, unit="")
        card_power.add(self.power_chart, 1)
        row.addWidget(card_power, 1)
        lay.addLayout(row, 2)

        card_cores = Card("Núcleos", theme.CPU, "uso por thread lógica")
        self.cores = CoreGrid()
        card_cores.add(self.cores, 1)
        lay.addWidget(card_cores, 2)

        bottom = QHBoxLayout()
        bottom.setSpacing(theme.scaled(theme.GAP))
        card_info = Card("Processador", theme.CPU)
        self.info = MetricList([
            ("name", "Modelo"), ("cores", "Núcleos / Threads"), ("base", "Clock base"),
            ("board", "Placa-mãe"), ("volts", "Tensão"), ("vid", "VID pedido"),
            ("uptime", "Ligado há"),
        ])
        card_info.add(self.info)
        card_info.body.addStretch(1)
        bottom.addWidget(card_info, 1)

        card_stats = Card("Sessão", theme.GPU, "mín / méd / máx")
        self.stats_rows = MetricList([
            ("usage", "Uso"), ("temp", "Temperatura"), ("power", "Potência"),
            ("clock", "Clock"),
        ])
        card_stats.add(self.stats_rows)
        card_stats.body.addStretch(1)
        bottom.addWidget(card_stats, 1)

        card_top = Card("Top processos por CPU", theme.RAM)
        self.top = MetricList([(f"p{i}", "—") for i in range(8)])
        card_top.add(self.top)
        card_top.body.addStretch(1)
        bottom.addWidget(card_top, 1)
        lay.addLayout(bottom, 2)
        lay.addStretch(0)

    def on_settings_changed(self) -> None:
        for chart in (self.chart, self.clock_chart, self.power_chart):
            chart.configure(**self.chart_config())
            chart.set_span(self.cfg.history_window)

    def _mostrar_tensao(self, d: dict) -> None:
        """Vcore e VID em linhas separadas, cada uma com a sua procedencia.

        Sao coisas diferentes e por muito tempo esta tela mostrou uma no lugar da
        outra: o VID e' o codigo que o nucleo PEDE, e nesta maquina ele marcava
        0,46 V com o pacote a 98 W — fisicamente impossivel. Quando o rail ainda
        nao foi identificado (precisa de carga variada) a linha some, porque um
        travessao aqui e' mais honesto que o numero errado que havia antes.
        """
        volts = d.get("cpu_volts")
        linha = self.info.row("volts")
        if linha is not None:
            linha.setVisible(volts is not None)
            if volts is not None:
                linha.set(f"{volts:.3f} V", theme.TXT)
                linha.set_stat(_FONTE_VOLTS.get(d.get("cpu_volts_src") or "", ""))

        vid = d.get("cpu_vid")
        linha = self.info.row("vid")
        if linha is not None:
            # Sem elevacao o VID trava no topo da codificacao (1,550 V) e vira
            # lixo com cara de medida; a faixa plausivel e' o filtro.
            valido = vid is not None and 0.3 < vid < 1.55
            linha.setVisible(valido)
            if valido:
                linha.set(f"{vid:.3f} V", theme.MUTE)
                linha.set_stat("tensão pedida pelo núcleo")

    def on_system(self, d: dict) -> None:
        if not d:
            return
        h = self.history
        pct = d.get("cpu_pct", 0.0)
        temp = d.get("cpu_temp")
        watts = d.get("cpu_watts")

        self.kpi.set("usage", f"{pct:.0f}", theme.load_color(pct),
                     self.app.stats.fmt("cpu_pct", 0, "%"))
        self.kpi.set("clock", f"{d.get('cpu_mhz', 0) / 1000:.2f}" if d.get("cpu_mhz")
                     else units.DASH, theme.TXT,
                     f"média {units.clock(d.get('cpu_mhz_avg'))}")
        self.kpi.set("temp", units.integer(temp), theme.temp_color(temp),
                     self.app.stats.fmt("cpu_temp", 0, "°"))
        self.kpi.set("power", f"{watts:.1f}" if watts is not None else units.DASH,
                     theme.watt_color(watts, 65, 110),
                     f"núcleos {units.watts(d.get('cpu_watts_cores'))}")
        self.kpi.set("fan", units.integer(d.get("cpu_fan")), theme.TXT,
                     f"{len(d.get('fans') or [])} ventoinhas")
        procs, threads = self.app.procs.totals()
        self.kpi.set("procs", str(procs or d.get("processes", 0)), theme.TXT,
                     f"{threads} threads")

        self.chart.set_values("usage", h.values("cpu_pct"))
        self.chart.set_values("temp", h.values("cpu_temp"))
        self.chart.refresh()
        self.clock_chart.set_values("clock", h.values("cpu_mhz"))
        self.clock_chart.refresh()
        self.power_chart.set_values("watts", h.values("cpu_watts"))
        self.power_chart.refresh()

        self.cores.set_data(d.get("cpu_core_loads") or d.get("cpu_cores_pct") or [],
                            d.get("cpu_core_clocks") or [])

        static = d.get("static", {})
        self.info.set("name", d.get("cpu_name") or static.get("cpu_name", units.DASH))
        self.info.set("cores", f"{static.get('cores', '?')} / {static.get('threads', '?')}")
        self.info.set("base", units.clock(static.get("cpu_base_mhz")))
        self.info.set("board", d.get("board_name") or units.DASH)
        self._mostrar_tensao(d)
        self.info.set("uptime", units.duration(d.get("uptime")))

        st = self.app.stats
        self.stats_rows.set("usage", st.fmt("cpu_pct", 0, "%") or units.DASH)
        self.stats_rows.set("temp", st.fmt("cpu_temp", 0, "°C") or units.DASH)
        self.stats_rows.set("power", st.fmt("cpu_watts", 1, " W") or units.DASH)
        self.stats_rows.set("clock", st.fmt("cpu_mhz", 0, " MHz") or units.DASH)

        procs_list = self.app.procs.snapshot()[:8]
        for i in range(8):
            row = self.top.row(f"p{i}")
            if row is None:
                continue
            if i < len(procs_list):
                p = procs_list[i]
                row.set_label(p.name[:26])
                row.set(f"{p.cpu:.1f}%", theme.load_color(p.cpu * 3))
            else:
                row.set_label("—")
                row.set(units.DASH, theme.MUTE)
