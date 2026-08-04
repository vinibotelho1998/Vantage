"""Tela de rede: throughput, latencia, jitter e perda de pacotes."""
from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout

from ... import theme
from ...core import units
from ..charts import Plot, TimeSeriesChart
from ..components import Card, KpiStrip, MetricList
from .base import View, scroll_page

_KPIS = [
    ("dl", "Download", ""), ("ul", "Upload", ""), ("ping", "Ping", "ms"),
    ("jitter", "Jitter", "ms"), ("loss", "Perda", "%"), ("total", "Sessão", ""),
]


class NetworkView(View):
    key = "network"
    title = "Rede"
    glyph = "≋"

    def __init__(self, app) -> None:
        super().__init__(app)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(theme.scaled(theme.GAP))

        self.kpi = KpiStrip(_KPIS, columns=6)
        root.addWidget(self.kpi)

        page, lay = scroll_page()
        root.addWidget(page, 1)

        card_tp = Card("Tráfego", theme.NET, "MB/s")
        self.tp_chart = TimeSeriesChart([
            Plot("dl", "Download", theme.NET, unit=" MB/s"),
            Plot("ul", "Upload", theme.FPS, unit=" MB/s"),
        ], y_max=None, height=200, unit="")
        card_tp.add(self.tp_chart, 1)
        lay.addWidget(card_tp, 3)

        card_ping = Card("Latência", theme.FPS, "ms até o host de teste")
        self.ping_chart = TimeSeriesChart([
            Plot("ping", "Ping", theme.FPS, unit=" ms"),
        ], y_max=None, height=175, unit="")
        card_ping.add(self.ping_chart, 1)
        lay.addWidget(card_ping, 2)

        row = QHBoxLayout()
        row.setSpacing(theme.scaled(theme.GAP))
        card_conn = Card("Conexão", theme.NET)
        self.conn_rows = MetricList([
            ("host", "Host de teste"), ("ping", "Ping atual"), ("jitter", "Jitter"),
            ("best", "Melhor"), ("worst", "Pior"), ("loss", "Perda de pacotes"),
        ])
        card_conn.add(self.conn_rows)
        card_conn.body.addStretch(1)
        row.addWidget(card_conn, 1)

        card_vol = Card("Volume", theme.DISK)
        self.vol_rows = MetricList([
            ("dl", "Download agora"), ("ul", "Upload agora"),
            ("tdl", "Baixado (desde o boot)"), ("tul", "Enviado (desde o boot)"),
            ("peak_dl", "Pico de download"), ("peak_ul", "Pico de upload"),
        ])
        card_vol.add(self.vol_rows)
        card_vol.body.addStretch(1)
        row.addWidget(card_vol, 1)

        card_stats = Card("Sessão", theme.GPU, "mín / méd / máx")
        self.stats_rows = MetricList([("ping", "Ping"), ("loss", "Perda")])
        card_stats.add(self.stats_rows)
        card_stats.body.addStretch(1)
        row.addWidget(card_stats, 1)
        lay.addLayout(row, 2)
        lay.addStretch(0)

        self._peak_dl = 0.0
        self._peak_ul = 0.0

    def on_settings_changed(self) -> None:
        for chart in (self.tp_chart, self.ping_chart):
            chart.configure(**self.chart_config())
            chart.set_span(self.cfg.history_window)

    def on_system(self, d: dict) -> None:
        if not d:
            return
        h = self.history
        dl, ul = d.get("net_dl", 0.0), d.get("net_ul", 0.0)
        self._peak_dl = max(self._peak_dl, dl)
        self._peak_ul = max(self._peak_ul, ul)
        ping = d.get("ping_ms")
        loss = d.get("packet_loss")

        self.kpi.set("dl", units.rate(dl).split(" ")[0], theme.NET, units.rate(dl))
        self.kpi.set("ul", units.rate(ul).split(" ")[0], theme.FPS, units.rate(ul))
        self.kpi.set("ping", units.integer(ping), theme.ping_color(ping),
                     self.app.stats.fmt("ping_ms", 0, " ms"))
        self.kpi.set("jitter", f"{d.get('ping_jitter'):.1f}" if d.get("ping_jitter")
                     is not None else units.DASH, theme.TXT)
        self.kpi.set("loss", f"{loss:.0f}" if loss is not None else units.DASH,
                     theme.loss_color(loss))
        self.kpi.set("total", units.size(d.get("net_total_dl", 0)).split(" ")[0], theme.TXT,
                     f"↓{units.size(d.get('net_total_dl'))} ↑{units.size(d.get('net_total_ul'))}")

        self.tp_chart.set_values("dl", [v / 1024 ** 2 for v in h.values("net_dl")])
        self.tp_chart.set_values("ul", [v / 1024 ** 2 for v in h.values("net_ul")])
        self.tp_chart.refresh()
        self.ping_chart.set_values("ping", h.values("ping_ms"))
        self.ping_chart.refresh()

        self.conn_rows.set("host", f"{self.cfg.ping_host}:{self.cfg.ping_port}")
        self.conn_rows.set("ping", units.ms(ping, 1), theme.ping_color(ping))
        self.conn_rows.set("jitter", units.ms(d.get("ping_jitter"), 1))
        self.conn_rows.set("best", units.ms(d.get("ping_best"), 1))
        self.conn_rows.set("worst", units.ms(d.get("ping_worst"), 1))
        self.conn_rows.set("loss", units.percent(loss, 1), theme.loss_color(loss))

        self.vol_rows.set("dl", units.rate(dl))
        self.vol_rows.set("ul", units.rate(ul))
        self.vol_rows.set("tdl", units.size(d.get("net_total_dl")))
        self.vol_rows.set("tul", units.size(d.get("net_total_ul")))
        self.vol_rows.set("peak_dl", units.rate(self._peak_dl))
        self.vol_rows.set("peak_ul", units.rate(self._peak_ul))

        st = self.app.stats
        self.stats_rows.set("ping", st.fmt("ping_ms", 0, " ms") or units.DASH)
        self.stats_rows.set("loss", st.fmt("packet_loss", 1, "%") or units.DASH)
