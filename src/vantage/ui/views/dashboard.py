"""Painel principal: visao geral de tudo em uma tela, pensada para segundo monitor."""
from __future__ import annotations

import math

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QVBoxLayout

from ... import theme
from ...core import frames as fr
from ...core import units
from ..charts import BarMeter, Gauge, Plot, Sparkline, TimeSeriesChart
from ..components import Badge, Card, KpiStrip, MetricList, dimm_color, label
from ..components import linha_opcional as _linha
from .base import View, scroll_page

_KPIS = [
    ("cpu", "CPU", "%"), ("cpu_temp", "CPU temp", "°C"),
    ("gpu", "GPU", "%"), ("gpu_temp", "GPU temp", "°C"),
    ("ram", "Memória", "%"), ("vram", "VRAM", "%"),
    ("fps", "FPS", ""), ("power", "Consumo", "W"),
]

_CARD_COM_MEDIDOR = 212
"""Largura de card abaixo da qual o medidor circular sai. Com ele, 212 px e' o
que ainda cabe "Frequência 6000 MHz" ao lado; e' a largura de cada card numa
janela de 1360 px."""


class DashboardView(View):
    key = "dashboard"
    title = "Painel"
    glyph = "▦"

    def __init__(self, app) -> None:
        super().__init__(app)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(theme.scaled(theme.GAP))

        self.kpi = KpiStrip(_KPIS, columns=8)
        root.addWidget(self.kpi)

        # O painel era a unica tela sem rolagem. Em janela baixa (notebook,
        # meia tela de um 1080p) o layout espremia tudo abaixo do minimo e os
        # chips da legenda caiam por cima do grafico; rolando, nada se sobrepoe.
        page, corpo = scroll_page()
        root.addWidget(page, 1)

        middle = QHBoxLayout()
        middle.setSpacing(theme.scaled(theme.GAP))
        self._cards: dict[str, Card] = {
            "timeline": self._build_timeline(),
            "fps": self._build_fps_card(),
        }
        middle.addWidget(self._cards["timeline"], 5)
        middle.addWidget(self._cards["fps"], 3)
        corpo.addLayout(middle, 5)

        self._grid = QGridLayout()
        self._grid.setSpacing(theme.scaled(theme.GAP))
        self._grid_keys = ("cpu", "gpu", "ram", "disk", "net")
        self._ocultos: set[str] = set()
        """Cards que a configuracao ou a maquina tiraram do painel.

        Guardado aqui, e nao lido de isHidden(): um widget recem-criado e sem
        pai responde escondido, e o grid nasceria vazio.
        """
        self._colunas = len(self._grid_keys)
        for key in self._grid_keys:
            self._cards[key] = getattr(self, f"_build_{key}")()
        self._gauges = (self.cpu_gauge, self.gpu_gauge, self.ram_gauge)
        self._relayout_cards()
        corpo.addLayout(self._grid, 4)

    def _relayout_cards(self) -> None:
        """Reencaixa os cards de peca contando so' os visiveis.

        Esconder um card sem refazer o grid deixa a coluna vazia no lugar: um
        buraco no meio do painel, que e' pior do que o card inutil que saiu.
        Quando eles nao cabem todos numa linha, a ultima linha, mais curta,
        divide a largura inteira entre os seus, em vez de deixar um vao.
        """
        while self._grid.count():
            self._grid.takeAt(0)
        for i in range(self._grid.columnCount()):
            self._grid.setColumnStretch(i, 0)
        visiveis = [self._cards[k] for k in self._grid_keys if k not in self._ocultos]
        if not visiveis:
            return
        colunas = max(1, min(self._colunas, len(visiveis)))
        linhas = math.ceil(len(visiveis) / colunas)
        sobra = len(visiveis) - (linhas - 1) * colunas
        # Unidades de coluna: as linhas cheias usam `sobra` unidades por card,
        # a ultima usa `colunas` por card, e as duas somam o mesmo total.
        unidades = colunas * sobra if 0 < sobra < colunas else colunas
        for i, card in enumerate(visiveis):
            linha, coluna = divmod(i, colunas)
            ultima = linha == linhas - 1 and sobra < colunas
            largura = colunas if ultima else (unidades // colunas)
            self._grid.addWidget(card, linha, coluna * largura, 1, largura)
        for i in range(unidades):
            self._grid.setColumnStretch(i, 1)
        self._encaixar_medidores()

    def _encaixar_medidores(self) -> None:
        """Tira os medidores circulares quando cada card fica estreito demais.

        O medidor tem largura fixa. Numa janela de notebook ele ficava e o que
        encolhia era a coluna de numeros, ate' o valor ser cortado; o medidor so'
        repete a porcentagem que a faixa do topo ja' mostra, entao e' ele que sai.
        """
        visiveis = sum(1 for k in self._grid_keys if not self._cards[k].isHidden())
        if not visiveis:
            return
        gap = theme.scaled(theme.GAP)
        por_card = (self.width() - gap * (visiveis - 1)) / visiveis
        mostrar = por_card >= theme.scaled(_CARD_COM_MEDIDOR)
        for gauge in self._gauges:
            if gauge.isHidden() == mostrar:
                gauge.setVisible(mostrar)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._encaixar_medidores()

    def _build_timeline(self) -> Card:
        card = Card("Linha do tempo", theme.accent_color(self.cfg.accent))
        self.chart = TimeSeriesChart([
            Plot("cpu", "CPU", theme.CPU),
            Plot("gpu", "GPU", theme.GPU),
            Plot("ram", "RAM", theme.RAM),
            Plot("vram", "VRAM", theme.DISK),
        ], y_max=100.0, height=200)
        self.chart.set_span(self.cfg.history_window)
        card.add(self.chart, 1)

        legend = QHBoxLayout()
        legend.setSpacing(theme.scaled(6))
        self._toggles: dict[str, Badge] = {}
        for key, name, color in (("cpu", "CPU", theme.CPU), ("gpu", "GPU", theme.GPU),
                                 ("ram", "RAM", theme.RAM), ("vram", "VRAM", theme.DISK)):
            chip = Badge(name, color)
            chip.setCursor(Qt.CursorShape.PointingHandCursor)
            chip.mousePressEvent = lambda _e, k=key: self._toggle(k)
            self._toggles[key] = chip
            legend.addWidget(chip)
            if key not in self.cfg.dashboard_plots:
                self.chart.toggle_plot(key)
                chip.set_color(theme.FAINT)
        legend.addStretch(1)
        self._span_label = label("", 7.5, QFont.Weight.Normal, theme.FAINT)
        legend.addWidget(self._span_label)
        card.add_layout(legend)
        return card

    def _toggle(self, key: str) -> None:
        self.chart.toggle_plot(key)
        plot = self.chart.plot(key)
        chip = self._toggles[key]
        chip.set_color(plot.color if plot.visible else theme.FAINT)
        self.cfg.dashboard_plots = [k for k in self._toggles
                                    if self.chart.plot(k).visible]
        self.cfg.save()

    def _build_fps_card(self) -> Card:
        card = Card("Jogo em foco", theme.FPS)
        self.game_badge = Badge("nenhum", theme.FAINT)
        card.add_header_widget(self.game_badge)

        hero = QHBoxLayout()
        hero.setSpacing(theme.scaled(12))
        col = QVBoxLayout()
        col.setSpacing(0)
        self.fps_value = label("—", 56, QFont.Weight.Bold, theme.MUTE, theme.FONT_DISPLAY)
        cap = label("FPS", 8, QFont.Weight.Bold, theme.FAINT)
        col.addWidget(self.fps_value)
        col.addWidget(cap)
        hero.addLayout(col)
        hero.addStretch(1)

        self.lows = MetricList([("avg", "Média"), ("low1", "1% Low"),
                                ("ft", "Frametime")])
        self.lows.setFixedWidth(theme.scaled(148))
        hero.addWidget(self.lows)
        card.add_layout(hero)

        chips = QHBoxLayout()
        chips.setSpacing(theme.scaled(6))
        self.bottleneck = Badge("—", theme.FAINT)
        self.smooth_badge = Badge("—", theme.FAINT)
        self.sync_badge = Badge("—", theme.FAINT)
        for b in (self.bottleneck, self.smooth_badge, self.sync_badge):
            chips.addWidget(b)
        chips.addStretch(1)
        card.add_layout(chips)

        # Frametime cru vira uma cerca de espetos: cada quadro ruim e' uma barra
        # inteira, e o desenho conta mais sobre densidade do que sobre a jogada.
        # Aqui vale a mesma leitura do overlay: linha de FPS por segundo, com os
        # lows por baixo, que e' onde a queda aparece.
        self.fps_chart = TimeSeriesChart([
            Plot("fps", "FPS", theme.FPS),
            Plot("low", "1% low", theme.WARN, width=1.4),
        ], y_max=None, height=118, unit="")
        self.fps_chart.set_span(self.cfg.history_window)
        card.add(self.fps_chart, 1)
        return card

    def _build_cpu(self) -> Card:
        card = Card("CPU", theme.CPU)
        row = QHBoxLayout()
        row.setSpacing(theme.scaled(10))
        self.cpu_gauge = Gauge(theme.CPU, 96)
        row.addWidget(self.cpu_gauge)
        self.cpu_rows = MetricList([("temp", "Temp"), ("freq", "Clock"),
                                    ("watts", "Potência"), ("volts", "Tensão"),
                                    ("fan", "Ventoinha")])
        row.addWidget(self.cpu_rows, 1)
        card.add_layout(row)
        self.cpu_spark = Sparkline(theme.CPU, 30, fixed_max=100)
        card.add(self.cpu_spark)
        return card

    def _build_gpu(self) -> Card:
        card = Card("GPU", theme.GPU)
        row = QHBoxLayout()
        row.setSpacing(theme.scaled(10))
        self.gpu_gauge = Gauge(theme.GPU, 96)
        row.addWidget(self.gpu_gauge)
        self.gpu_rows = MetricList([("temp", "Temp"), ("freq", "Clock"),
                                    ("watts", "Potência"), ("volts", "Tensão"),
                                    ("vram", "VRAM"), ("vram_temp", "Temp VRAM")])
        row.addWidget(self.gpu_rows, 1)
        card.add_layout(row)
        self.gpu_spark = Sparkline(theme.GPU, 30, fixed_max=100)
        card.add(self.gpu_spark)
        return card

    def _build_ram(self) -> Card:
        card = Card("Memória", theme.RAM)
        row = QHBoxLayout()
        row.setSpacing(theme.scaled(10))
        self.ram_gauge = Gauge(theme.RAM, 96)
        row.addWidget(self.ram_gauge)
        self.ram_rows = MetricList([("used", "Em uso"), ("avail", "Disponível"),
                                    ("jogo", "Jogo em foco"), ("temp", "Temp"),
                                    ("freq", "Frequência"), ("swap", "Paginação")])
        row.addWidget(self.ram_rows, 1)
        card.add_layout(row)
        self.ram_spark = Sparkline(theme.RAM, 30, fixed_max=100)
        card.add(self.ram_spark)
        return card

    def _build_disk(self) -> Card:
        card = Card("Armazenamento", theme.DISK)
        self.disk_rows = MetricList([("used", "Sistema"), ("temp", "Temp"),
                                     ("read", "Leitura"), ("write", "Escrita")])
        card.add(self.disk_rows)
        self.disk_bar = BarMeter(theme.DISK)
        card.add(self.disk_bar)
        self.disk_spark = Sparkline(theme.DISK, 34)
        card.add(self.disk_spark, 1)
        return card

    def _build_net(self) -> Card:
        card = Card("Rede", theme.NET)
        self.net_rows = MetricList([("dl", "Download"), ("ul", "Upload"),
                                    ("ping", "Ping"), ("jitter", "Jitter")])
        card.add(self.net_rows)
        self.net_spark = Sparkline(theme.NET, 46)
        card.add(self.net_spark, 1)
        return card

    def on_settings_changed(self) -> None:
        wanted = set(self.cfg.dash_cards)
        for key, card in self._cards.items():
            card.setVisible(key in wanted)
        self._ocultos = {k for k in self._grid_keys if k not in wanted}
        self._relayout_cards()
        self.fps_chart.setVisible("frametime" in wanted)
        self.chart.configure(legend=False, **self.chart_config())
        self.chart.set_span(self.cfg.history_window)
        self.fps_chart.configure(**self.chart_config())
        self.fps_chart.set_span(self.cfg.history_window)
        for spark in (self.cpu_spark, self.gpu_spark, self.ram_spark,
                      self.disk_spark, self.net_spark):
            spark.configure(self.cfg.smooth_lines)

    def _ajustar_disponivel(self, d: dict, gpu: dict) -> None:
        """Mostra so' o que essa maquina tem como medir.

        Sem LibreHardwareMonitor nao ha' temperatura nem potencia; sem GPU
        dedicada nao ha' VRAM. Deixar esses tiles no lugar, eternamente com
        travessao, e' informacao que nao informa; e' o que faz o app parecer
        quebrado em quem so' nao tem o sensor.
        """
        tem_sensores = bool(d.get("lhm_ok"))
        tem_gpu = bool(gpu)
        visiveis = ["cpu", "ram", "fps"]
        if tem_sensores:
            visiveis.append("cpu_temp")
        if tem_gpu:
            visiveis.append("gpu")
            if gpu.get("temp") is not None or gpu.get("temp_hotspot") is not None:
                visiveis.append("gpu_temp")
            if gpu.get("vram_total"):
                visiveis.append("vram")
        if tem_sensores or gpu.get("watts") is not None:
            visiveis.append("power")
        self.kpi.show_only(visiveis)
        mostrar_gpu = tem_gpu and "gpu" in self.cfg.dash_cards
        if ("gpu" not in self._ocultos) != mostrar_gpu:
            self._cards["gpu"].setVisible(mostrar_gpu)
            if mostrar_gpu:
                self._ocultos.discard("gpu")
            else:
                self._ocultos.add("gpu")
            self._relayout_cards()

    def on_system(self, d: dict) -> None:
        if not d:
            return
        h = self.history
        gpu = d.get("gpu") or {}
        self._ajustar_disponivel(d, gpu)

        for key, values in (("cpu", h.values("cpu_pct")), ("gpu", h.values("gpu_pct")),
                            ("ram", h.values("ram_pct")), ("vram", h.values("vram_pct"))):
            self.chart.set_values(key, values)
        self.chart.refresh()
        self._span_label.setText(f"últimos {self.cfg.history_window}s")

        self.fps_chart.set_values("fps", h.values("fps"))
        self.fps_chart.set_values("low", h.values("fps_low1"))
        self.fps_chart.refresh()

        cpu = d.get("cpu_pct", 0.0)
        ct = d.get("cpu_temp")
        self.kpi.set("cpu", f"{cpu:.0f}", theme.load_color(cpu),
                     f"{d.get('cpu_mhz', 0) / 1000:.2f} GHz" if d.get("cpu_mhz") else "")
        self.kpi.set("cpu_temp", units.integer(ct), theme.temp_color(ct),
                     self.app.stats.fmt("cpu_temp", 0, "°"))
        gu = gpu.get("usage")
        gt = gpu.get("temp")
        self.kpi.set("gpu", units.integer(gu), theme.load_color(gu),
                     f"{gpu.get('freq', 0)} MHz" if gpu.get("freq") else "")
        self.kpi.set("gpu_temp", units.integer(gt), theme.temp_color(gt),
                     self.app.stats.fmt("gpu_temp", 0, "°"))
        rp = d.get("ram_pct")
        self.kpi.set("ram", units.integer(rp), theme.load_color(rp),
                     f"{d.get('ram_used', 0):.1f} / {d.get('ram_total', 0):.0f} GB")
        vp = gpu.get("vram_pct")
        self.kpi.set("vram", units.integer(vp), theme.load_color(vp),
                     units.mib_pair(gpu.get("vram_used"), gpu.get("vram_total")))
        total_w = (d.get("cpu_watts") or 0) + (gpu.get("watts") or 0)
        self.kpi.set("power", f"{total_w:.0f}" if total_w else units.DASH, theme.TXT,
                     f"CPU {units.watts(d.get('cpu_watts'), 0)} · GPU "
                     f"{units.watts(gpu.get('watts'), 0)}")

        self.cpu_gauge.set_value(cpu, units.temp(ct), theme.load_color(cpu))
        self.cpu_rows.set("temp", units.temp(ct), theme.temp_color(ct))
        self.cpu_rows.set("freq", units.clock(d.get("cpu_mhz")))
        self.cpu_rows.set("watts", units.watts(d.get("cpu_watts")))
        # Linha sem sensor some em vez de virar travessao: o Vcore so' aparece
        # depois de o rail ser identificado, e nem toda placa entrega um.
        _linha(self.cpu_rows, "volts", d.get("cpu_volts"),
               lambda v: f"{v:.3f} V", theme.TXT)
        self.cpu_rows.set("fan", units.rpm(d.get("cpu_fan")))
        self.cpu_spark.set_values(h.values("cpu_pct"))

        self.gpu_gauge.set_value(gu, units.temp(gt), theme.load_color(gu))
        self.gpu_rows.set("temp", units.temp(gt), theme.temp_color(gt))
        self.gpu_rows.set("freq", units.mhz(gpu.get("freq")))
        gw = gpu.get("watts")
        self.gpu_rows.set("watts", ("~" if gpu.get("watts_estimated") else "")
                          + units.watts(gw, 0))
        _linha(self.gpu_rows, "volts", gpu.get("volts"), lambda v: f"{v:.3f} V", theme.TXT)
        # Mesma regra do tile: sem os dois sensores de memoria a linha some, em
        # vez de repetir um travessao que se le' como defeito da placa.
        _linha(self.gpu_rows, "vram", gpu.get("vram_pct"),
               lambda _v: units.mib_pair(gpu.get("vram_used"), gpu.get("vram_total")),
               theme.load_color)
        _linha(self.gpu_rows, "vram_temp", gpu.get("temp_vram"), units.temp,
               theme.vram_temp_color)
        self.gpu_spark.set_values(h.values("gpu_pct"))

        self.ram_gauge.set_value(rp, units.gib(d.get("ram_used")), theme.load_color(rp))
        self.ram_rows.set("used", f"{d.get('ram_used', 0):.1f} / {d.get('ram_total', 0):.0f} GB")
        self.ram_rows.set("avail", units.gib(d.get("ram_avail")))
        # Private bytes, e nao o working set: o Windows poda o residente quando a
        # janela perde o foco, e num alt-tab o numero afundaria sem o jogo ter
        # liberado nada. A linha inteira some quando nao ha' jogo em foco.
        _linha(self.ram_rows, "jogo", d.get("game_ram_private"),
               lambda v: units.gib(v / 1024), theme.RAM)
        self.ram_rows.set_label("jogo", d.get("game_name") or "Jogo em foco")
        _linha(self.ram_rows, "temp", d.get("ram_temp"), units.temp, dimm_color(d))
        self.ram_rows.set("freq", units.mhz(d.get("ram_freq")))
        self.ram_rows.set("swap", f"{d.get('swap_used', 0):.1f} GB",
                          theme.load_color(d.get("swap_pct")))
        self.ram_spark.set_values(h.values("ram_pct"))

        self.disk_rows.set("used", f"{d.get('disk_used', 0):.0f} / "
                                   f"{d.get('disk_total', 0):.0f} GB")
        nt = d.get("nvme_temp")
        self.disk_rows.set("temp", units.temp(nt), theme.temp_color(nt))
        self.disk_rows.set("read", units.rate(d.get("disk_r")))
        self.disk_rows.set("write", units.rate(d.get("disk_w")))
        self.disk_bar.set_value(d.get("disk_pct"), theme.load_color(d.get("disk_pct")))
        self.disk_spark.set_values([a + b for a, b in
                                    zip(h.values("disk_r"), h.values("disk_w"), strict=False)])

        self.net_rows.set("dl", units.rate(d.get("net_dl")))
        self.net_rows.set("ul", units.rate(d.get("net_ul")))
        ping = d.get("ping_ms")
        self.net_rows.set("ping", units.ms(ping, 0), theme.ping_color(ping))
        self.net_rows.set("jitter", units.ms(d.get("ping_jitter"), 1))
        self.net_spark.set_values([a + b for a, b in
                                   zip(h.values("net_dl"), h.values("net_ul"), strict=False)])

    def on_fps(self) -> None:
        stream = self.app.active_stream()
        if stream is None:
            # O tile da faixa estava na lista e nunca recebia valor: travessao
            # para sempre, mesmo com o jogo a 140 fps no card logo abaixo.
            self.kpi.set("fps", units.DASH, theme.MUTE, "nenhum jogo")
            self.fps_value.setText("—")
            self.fps_value.setStyleSheet(f"color: {theme.MUTE};")
            self.game_badge.update_badge("nenhum jogo", theme.FAINT)
            # O tile de FPS da faixa nunca era preenchido: ficava com travessao
            # com o jogo rodando a 140 no card logo abaixo.
            self.kpi.set("fps", units.DASH, theme.MUTE, "sem jogo em foco")
            for key in ("avg", "low1", "ft"):
                self.lows.set(key, units.DASH, theme.MUTE)
            self.bottleneck.update_badge(self.app.fps_hint(), theme.FAINT)
            self.smooth_badge.update_badge("—", theme.FAINT)
            self.sync_badge.update_badge("—", theme.FAINT)
            return

        m = stream.metrics
        now = m.fps_now or m.fps_avg
        self.kpi.set("fps", units.integer(now), theme.fps_color(now),
                     f"1% low {units.integer(m.low_1)}")
        self.fps_value.setText(units.integer(now))
        self.fps_value.setStyleSheet(f"color: {theme.fps_color(now)};")
        self.game_badge.update_badge(stream.app or "?", theme.FPS)
        self.kpi.set("fps", units.integer(now), theme.fps_color(now),
                     f"1% low {units.integer(m.low_1)}")
        self.lows.set("avg", units.integer(m.fps_avg), theme.fps_color(m.fps_avg))
        self.lows.set("low1", units.integer(m.low_1), theme.fps_color(m.low_1))
        self.lows.set("ft", units.ms(m.ft_avg, 2), theme.frametime_color(m.ft_avg))
        self.bottleneck.update_badge(
            f"gargalo: {m.bottleneck}",
            theme.CPU if m.bottleneck == fr.BOTTLENECK_CPU else
            (theme.GPU if m.bottleneck == fr.BOTTLENECK_GPU else theme.MUTE))
        # O rotulo cabe em duas palavras; o porque (quantos por cento dos quadros,
        # ou que a captura nao traz as colunas) fica no tooltip.
        self.bottleneck.setToolTip(m.bottleneck_detail)
        self.smooth_badge.update_badge(
            f"fluidez {m.smoothness:.0f}" if m.smoothness is not None else "fluidez indisponível",
            theme.score_color(m.smoothness))
        self.smooth_badge.setToolTip(
            f"variação típica entre quadros vizinhos: {m.ft_jitter:.2f} ms"
            if m.ft_jitter is not None else "")
        self.sync_badge.update_badge(
            "VSync ligado" if stream.vsync else "VSync desligado",
            theme.WARN if stream.vsync else theme.OK)

