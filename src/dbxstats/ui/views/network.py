"""Tela de rede: throughput, latencia, jitter, perda de pacotes e teste de banda."""
from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QHBoxLayout, QProgressBar, QVBoxLayout

from ... import theme
from ...core import units
from ...sensors import speedtest
from ..charts import Plot, TimeSeriesChart
from ..components import Badge, Card, KpiStrip, MetricList, PillButton, StatTile, label
from .base import View, scroll_page

_KPIS = [
    ("dl", "Download", ""), ("ul", "Upload", ""), ("ping", "Ping", "ms"),
    ("jitter", "Jitter", "ms"), ("loss", "Perda", "%"), ("total", "Sessão", ""),
]

_TESTE_KPIS = [
    ("dl", "Download", "Mbps"), ("ul", "Upload", "Mbps"), ("ping", "Latência", "ms"),
]

_ROTULO_FASE = {
    speedtest.FASE_OCIOSO: ("mede quando você mandar", theme.FAINT),
    speedtest.FASE_LATENCIA: ("medindo a latência…", theme.FPS),
    speedtest.FASE_DOWNLOAD: ("medindo o download…", theme.NET),
    speedtest.FASE_UPLOAD: ("medindo o upload…", theme.FPS),
    speedtest.FASE_PRONTO: ("medição concluída", theme.OK),
    speedtest.FASE_CANCELADO: ("teste interrompido", theme.WARN),
    speedtest.FASE_ERRO: ("não deu para medir", theme.BAD),
}


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

        lay.addWidget(self._montar_teste())

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

    # ── teste de velocidade ──────────────────────────────────────────────────
    def _montar_teste(self) -> Card:
        """Card do teste sob demanda: botao, barra, tres numeros e o detalhe."""
        accent = theme.accent_color(self.cfg.accent)
        card = Card("Teste de velocidade", accent, "download, upload e latência do link")

        barra = QHBoxLayout()
        barra.setSpacing(theme.scaled(8))
        self.test_btn = PillButton("Testar velocidade", accent, filled=True)
        self.test_btn.clicked.connect(self._alternar_teste)
        barra.addWidget(self.test_btn)
        barra.addStretch(1)
        self.test_badge = Badge(_ROTULO_FASE[speedtest.FASE_OCIOSO][0], theme.FAINT)
        barra.addWidget(self.test_badge)
        card.add_layout(barra)

        self.test_bar = QProgressBar()
        self.test_bar.setTextVisible(False)
        self.test_bar.setFixedHeight(theme.scaled(6))
        self.test_bar.setRange(0, 1000)
        self.test_bar.setValue(0)
        card.add(self.test_bar)

        # Tres tiles soltos, e nao uma KpiStrip: a faixa que reflui existe para a
        # barra de KPI da tela inteira, que muda de tamanho conforme a maquina.
        # Aqui sao sempre estes tres numeros, lado a lado.
        numeros = QHBoxLayout()
        numeros.setSpacing(theme.scaled(theme.GAP))
        self.test_tiles: dict[str, StatTile] = {}
        for chave, legenda, unidade in _TESTE_KPIS:
            tile = StatTile(legenda, unidade)
            self.test_tiles[chave] = tile
            numeros.addWidget(tile, 1)
        card.add_layout(numeros)

        self.test_rows = MetricList([
            ("servidor", "Servidor de teste"), ("jitter", "Jitter"),
            ("quando", "Última medição"),
        ])
        card.add(self.test_rows)

        # Recado do motor (erro ou ressalva). Fica escondido quando nao ha' nada
        # a dizer para o card nao carregar uma linha vazia o tempo todo.
        self.test_msg = label("", 8, QFont.Weight.Normal, theme.MUTE)
        self.test_msg.setWordWrap(True)
        self.test_msg.setVisible(False)
        card.add(self.test_msg)

        self._teste = speedtest.TesteDeVelocidade()
        self._teste_timer = QTimer(self)
        self._teste_timer.setInterval(120)
        self._teste_timer.timeout.connect(self._atualizar_teste)
        # O app nao avisa view nenhuma que vai fechar; sem este gancho, sair no
        # meio de um teste deixaria os fluxos baixando com a janela ja' fechada.
        qt = QApplication.instance()
        if qt is not None:
            qt.aboutToQuit.connect(self._teste.stop)
        self._atualizar_teste()
        return card

    def _alternar_teste(self) -> None:
        if self._teste.rodando:
            self._teste.cancel()
        elif self._teste.start():
            self._teste_timer.start()
        self._atualizar_teste()

    def _atualizar_teste(self) -> None:
        s = self._teste.snapshot()
        fase, rodando = s["fase"], s["rodando"]
        if not rodando:
            self._teste_timer.stop()

        self.test_btn.setText("Cancelar teste" if rodando else "Testar velocidade")
        self.test_btn.set_color(theme.BAD if rodando
                                else theme.accent_color(self.cfg.accent))
        texto, cor = _ROTULO_FASE.get(fase, _ROTULO_FASE[speedtest.FASE_OCIOSO])
        self.test_badge.update_badge(texto, cor)
        self.test_bar.setValue(int(s["progresso"] * 1000))

        # Enquanto a fase corre, o tile dela mostra a parcial em cinza: e' um
        # numero vivo, ainda nao o resultado — pintar de cor final daria ao
        # aquecimento do TCP a mesma autoridade da medida fechada.
        parcial = s["parcial"] if rodando else None
        for chave, valor, cor_final, fase_da_vez in (
                ("dl", s["download"], theme.NET, speedtest.FASE_DOWNLOAD),
                ("ul", s["upload"], theme.FPS, speedtest.FASE_UPLOAD)):
            medindo = fase == fase_da_vez and parcial is not None
            self.test_tiles[chave].set(units.mbps(parcial if medindo else valor),
                                       theme.MUTE if medindo else cor_final,
                                       "medindo…" if medindo else "")
        self.test_tiles["ping"].set(units.integer(s["ping"]), theme.ping_color(s["ping"]))

        self.test_rows.set("servidor", s["servidor"] or units.DASH)
        self.test_rows.set("jitter", units.ms(s["jitter"], 1))
        self.test_rows.set("quando", s["quando"] or units.DASH)

        recado = s["erro"] or s["aviso"] or ""
        self.test_msg.setText(recado)
        self.test_msg.setStyleSheet(
            f"color: {theme.BAD if s['erro'] else theme.MUTE}; background: transparent;")
        self.test_msg.setVisible(bool(recado))

    def on_settings_changed(self) -> None:
        if not self._teste.rodando:
            self.test_btn.set_color(theme.accent_color(self.cfg.accent))
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
