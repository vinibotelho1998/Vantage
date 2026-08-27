"""Tela de rede: throughput, latencia, jitter, perda de pacotes e teste de banda."""
from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QHBoxLayout,
    QProgressBar,
    QVBoxLayout,
)

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

_AUTOMATICO = "Automático (menor latência)"
"""Primeira opção da lista de servidores, e o padrão, sempre."""


def _taxa(mbps: float | None) -> str:
    """Mbps ou Gbps conforme o tamanho: "13559 Mbps" ninguém lê de primeira."""
    if not mbps:
        return units.DASH
    return f"{mbps / 1000:.1f} Gbps".replace(".", ",") if mbps >= 1000 else f"{mbps:.0f} Mbps"


def _texto_servidor(s: dict) -> str:
    """Quem está medindo, onde fica e a que distância, numa linha só.

    A latência que sai aqui é a de QUEM ESTÁ MEDINDO, e não a do servidor
    escolhido no começo: quando a fila desce para a reserva, casar o host de um
    com o número do outro seria inventar uma medida que ninguém fez.
    """
    host = s.get("servidor")
    if not host:
        return units.DASH
    nome = s.get("servidor_nome")
    texto = host if not nome or nome == host else f"{nome} ({host})"
    ms = s.get("servidor_ms")
    if ms is not None:
        texto += f" · {units.ms(ms, 1)}"
    if s.get("fixado"):
        texto += " · fixado"
    return texto


def _texto_teto(s: dict) -> str:
    """O menor teto medido do envio, e de quem ele é.

    Existe para responder à pergunta que um número alto de upload sempre levanta:
    isso é a minha internet ou é o app? Quando o teto está muito acima do medido,
    a resposta é "internet" e a linha serve de prova; quando não está, o aviso
    logo abaixo diz que o número virou o limite do envio.
    """
    janela, processo = s.get("teto_janela"), s.get("teto_processo")
    if janela and (not processo or janela <= processo):
        return f"{_taxa(janela)} · janela de envio do sistema"
    if processo:
        return f"{_taxa(processo)} · este app, com um núcleo"
    return units.DASH


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

    def _montar_teste(self) -> Card:
        """Card do teste sob demanda: botao, barra, tres numeros e o detalhe."""
        accent = theme.accent_color(self.cfg.accent)
        card = Card("Teste de velocidade", accent, "download, upload e latência do link")

        self._teste = speedtest.TesteDeVelocidade()

        barra = QHBoxLayout()
        barra.setSpacing(theme.scaled(8))
        self.test_btn = PillButton("Testar velocidade", accent, filled=True)
        self.test_btn.clicked.connect(self._alternar_teste)
        barra.addWidget(self.test_btn)
        # Escolher servidor a mao e' opcional de proposito: no automatico o motor
        # sonda todas as casas antes de medir e usa a mais proxima, que e' o certo
        # em quase todo caso. A lista existe para quem tem um servidor melhor (o
        # do proprio provedor, por exemplo) ou quer comparar com o Ookla usando a
        # mesma casa: sem isso, "por que o numero deles e' outro?" nao tem
        # resposta possivel.
        self.test_srv = QComboBox()
        self.test_srv.setMinimumWidth(theme.scaled(210))
        self.test_srv.setToolTip("Servidor de teste. No automático o app mede a "
                                 "latência de cada casa antes de começar e usa a "
                                 "mais próxima.")
        self._montar_servidores()
        self.test_srv.currentIndexChanged.connect(self._fixar_servidor)
        barra.addWidget(self.test_srv)
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
            ("servidor", "Servidor de teste"), ("envio", "Servidor de upload"),
            ("jitter", "Jitter"), ("teto", "Teto do envio"),
            ("quando", "Última medição"),
        ])
        card.add(self.test_rows)
        # Duas linhas que so' aparecem quando tem o que dizer: o servidor de
        # upload, quando ele nao e' o mesmo do download, e o teto do envio, que
        # so' existe depois de uma medicao de upload. Travessao fixo numa linha
        # diz "isto quebrou", e nao e' o caso.
        for chave in ("envio", "teto"):
            self.test_rows.row(chave).setVisible(False)

        # Recado do motor (erro ou ressalva). Fica escondido quando nao ha' nada
        # a dizer para o card nao carregar uma linha vazia o tempo todo.
        self.test_msg = label("", 8, QFont.Weight.Normal, theme.MUTE)
        self.test_msg.setWordWrap(True)
        self.test_msg.setVisible(False)
        card.add(self.test_msg)

        self._teste_timer = QTimer(self)
        self._teste_timer.setInterval(120)
        self._teste_timer.timeout.connect(self._atualizar_teste)
        # O app nao avisa view nenhuma que vai fechar; sem este gancho, sair no
        # meio de um teste deixaria os fluxos baixando com a janela ja' fechada.
        qt = QApplication.instance()
        if qt is not None:
            qt.aboutToQuit.connect(self._encerrar_teste)
        self._atualizar_teste()
        return card

    def _montar_servidores(self) -> None:
        """Preenche a lista de servidores com o que o motor de fato usaria.

        Nao adianta oferecer uma casa que o motor nao conhece, entao a lista sai
        dele: semente embutida mais o que a lista publica ja' deixou no disco. Um
        servidor fixado que sumiu da lista continua aparecendo: apagar da tela a
        escolha que ainda esta' valendo seria mentir sobre o proprio estado.
        """
        fixado = self._teste.fixado
        self.test_srv.blockSignals(True)
        self.test_srv.clear()
        self.test_srv.addItem(_AUTOMATICO, "")
        for prov in self._teste.candidatos():
            self.test_srv.addItem(f"{prov.rotulo} ({prov.host})", prov.host)
        if fixado and self.test_srv.findData(fixado) < 0:
            self.test_srv.addItem(f"{fixado} (fixado)", fixado)
        self.test_srv.setCurrentIndex(max(0, self.test_srv.findData(fixado or "")))
        self.test_srv.blockSignals(False)

    def _servidores_esperados(self) -> list[str]:
        hosts = [p.host for p in self._teste.candidatos()]
        fixado = self._teste.fixado
        if fixado and fixado not in hosts:
            hosts.append(fixado)
        return hosts

    def _sincronizar_servidores(self) -> None:
        """Casas novas da lista pública aparecem sem reabrir o app.

        A busca da lista roda em segundo plano e só termina depois que o teste já
        começou, então o que ela traz nunca está na tela no momento em que chega.
        Reconstruir a lista custa nada e só acontece quando ela de fato mudou:
        mexer no combo à toa roubaria a seleção de quem estivesse escolhendo.
        """
        atual = [self.test_srv.itemData(i) for i in range(1, self.test_srv.count())]
        if atual != self._servidores_esperados():
            self._montar_servidores()

    def _fixar_servidor(self, _indice: int) -> None:
        """Troca de servidor vale do proximo teste em diante, e fica gravada."""
        self._teste.fixar(self.test_srv.currentData() or None)
        self._atualizar_teste()

    def _encerrar_teste(self) -> None:
        """Fechar o app: manda parar e espera pouco, nunca o timeout do socket.

        `cancel()` derruba os sockets sem esperar quem esta' lendo, entao os
        fluxos saem quase na hora. A espera curta existe so' para o caso raro de
        um fluxo teimoso: segurar a saida do app por segundos seria trocar um
        congelamento por outro.
        """
        self._teste_timer.stop()
        self._teste.stop(0.5)

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
        # Medicao que fechou faltando um pedaco (download fora, servidor reserva,
        # fluxo que caiu) nao pode receber o mesmo verde de uma medicao limpa: o
        # aviso logo abaixo passaria batido e o numero seria lido como definitivo.
        if fase == speedtest.FASE_PRONTO and s["aviso"]:
            texto, cor = "medição concluída, com ressalva", theme.WARN
        self.test_badge.update_badge(texto, cor)
        self.test_bar.setValue(int(s["progresso"] * 1000))

        # Enquanto a fase corre, o tile dela mostra a parcial em cinza: e' um
        # numero vivo, ainda nao o resultado: pintar de cor final daria ao
        # aquecimento do TCP a mesma autoridade da medida fechada.
        #
        # Quem manda no "medindo…" e' a FASE, e nao a existencia da parcial: o
        # motor so' publica parcial quando byte novo chegou, e enquanto ele nao
        # chega o tile fica no travessao: dizer "0.0 Mbps · medindo…" enquanto se
        # espera o primeiro byte era inventar numero no lugar de "ainda nao sei".
        parcial = s["parcial"] if rodando else None
        for chave, valor, cor_final, fase_da_vez in (
                ("dl", s["download"], theme.NET, speedtest.FASE_DOWNLOAD),
                ("ul", s["upload"], theme.FPS, speedtest.FASE_UPLOAD)):
            medindo = rodando and fase == fase_da_vez
            vivo = parcial if (medindo and parcial is not None) else valor
            self.test_tiles[chave].set(units.mbps(vivo),
                                       theme.MUTE if medindo else cor_final,
                                       "medindo…" if medindo else "")
        self.test_tiles["ping"].set(units.integer(s["ping"]), theme.ping_color(s["ping"]))

        # Trocar de servidor no meio da medicao nao teria efeito nenhum sobre ela;
        # deixar a lista clicavel seria oferecer um botao que nao faz o que
        # parece.
        self.test_srv.setEnabled(not rodando)
        if not rodando:
            self._sincronizar_servidores()

        self.test_rows.set("servidor", _texto_servidor(s))
        self.test_rows.set("jitter", units.ms(s["jitter"], 1))
        self.test_rows.set("quando", s["quando"] or units.DASH)

        # O upload so' ganha linha propria quando mediu em outra casa: repetir o
        # mesmo host duas vezes seguidas nao informa nada.
        envio = s.get("servidor_envio")
        outro = bool(envio) and envio != s.get("servidor")
        self.test_rows.row("envio").setVisible(outro)
        if outro:
            self.test_rows.set("envio", envio)

        # O teto so' aparece depois que houve upload, e, quando o numero medido
        # encosta nele, o recado ambar logo abaixo explica que o valor virou o
        # limite do envio, e nao a velocidade do link.
        teto = _texto_teto(s)
        self.test_rows.row("teto").setVisible(teto != units.DASH)
        self.test_rows.set("teto", teto, theme.MUTE)

        # O erro pode chegar com o teste ainda rodando (o download morre e o
        # upload continua), e e' de proposito: esconder a falha ate o fim deixava
        # o usuario encarando um tile vazio sem saber que ja' nao havia o que
        # esperar. Ressalva sai em ambar, nao em cinza, senao ninguem le'.
        recado = s["erro"] or s["aviso"] or ""
        self.test_msg.setText(recado)
        self.test_msg.setStyleSheet(
            f"color: {theme.BAD if s['erro'] else theme.WARN}; background: transparent;")
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
