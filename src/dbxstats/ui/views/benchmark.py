"""Tela de benchmark: captura uma corrida, resume e exporta."""
from __future__ import annotations

from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QHBoxLayout,
    QMenu,
    QPlainTextEdit,
    QProgressBar,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from ... import theme
from ...core import export
from ...core import frames as fr
from ...core import units
from ..charts import FrameTimeChart, Histogram
from ..components import Badge, Card, KpiStrip, MetricList, PillButton, label
from .base import View, scroll_page

_KPIS = [
    ("avg", "FPS médio", ""), ("low1", "1% Low", ""),
    ("ft", "Frametime", "ms"), ("stutter", "Stutter", "%"), ("smooth", "Fluidez", ""),
]


class BenchmarkView(View):
    key = "benchmark"
    title = "Benchmark"
    glyph = "◔"

    def __init__(self, app) -> None:
        super().__init__(app)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(theme.scaled(theme.GAP))

        bar = QHBoxLayout()
        bar.setSpacing(theme.scaled(8))
        self.run_btn = PillButton("Iniciar benchmark", theme.accent_color(self.cfg.accent),
                                  filled=True)
        self.run_btn.clicked.connect(self._toggle)
        bar.addWidget(self.run_btn)
        self.dur_btn = PillButton(f"Duração: {self.cfg.bench_seconds}s", theme.MUTE)
        self.dur_btn.clicked.connect(self._pick_duration)
        bar.addWidget(self.dur_btn)
        self.export_btn = PillButton("Exportar CSV", theme.MUTE)
        self.export_btn.clicked.connect(self._export)
        bar.addWidget(self.export_btn)
        bar.addStretch(1)
        self.target = Badge("nenhum jogo", theme.FAINT)
        bar.addWidget(self.target)
        root.addLayout(bar)

        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(theme.scaled(6))
        self.progress.setRange(0, 1000)
        self.progress.setValue(0)
        root.addWidget(self.progress)

        self.kpi = KpiStrip(_KPIS, columns=6)
        root.addWidget(self.kpi)

        page, lay = scroll_page()
        root.addWidget(page, 1)

        # As sessoes vem primeiro porque sao o que a aba existe para mostrar: o
        # jogo como ele foi, do inicio ao fim. A corrida cronometrada continua
        # abaixo, para quando se quer comparar um trecho especifico.
        self.card_sessoes = Card("Sessões de jogo", theme.FPS,
                                 "gravadas do início ao fim ao abrir pelos Atalhos")
        self.tabela = QTableWidget(0, len(_COLUNAS_SESSAO))
        self.tabela.setHorizontalHeaderLabels(_COLUNAS_SESSAO)
        self.tabela.verticalHeader().setVisible(False)
        self.tabela.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.tabela.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.tabela.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.tabela.setAlternatingRowColors(True)
        self.tabela.setMinimumHeight(theme.scaled(190))
        self.tabela.horizontalHeader().setStretchLastSection(True)
        self.tabela.itemSelectionChanged.connect(self._sessao_escolhida)
        self.card_sessoes.add(self.tabela, 1)

        acoes = QHBoxLayout()
        acoes.setSpacing(theme.scaled(8))
        self.btn_exp_sessao = PillButton("Exportar esta sessão", theme.MUTE)
        self.btn_exp_sessao.clicked.connect(self._exportar_sessao)
        self.btn_exp_todas = PillButton("Exportar todas", theme.MUTE)
        self.btn_exp_todas.clicked.connect(self._exportar_sessoes)
        acoes.addWidget(self.btn_exp_sessao)
        acoes.addWidget(self.btn_exp_todas)
        acoes.addStretch(1)
        self.aviso_sessao = label("", 8.5, color=theme.MUTE)
        acoes.addWidget(self.aviso_sessao)
        self.card_sessoes.add_layout(acoes)
        lay.addWidget(self.card_sessoes, 2)

        card_ft = Card("Frametime da corrida", theme.FRAME)
        self.ft_chart = FrameTimeChart(height=200)
        card_ft.add(self.ft_chart, 1)
        lay.addWidget(card_ft, 3)

        # A curva de percentis saiu: ela conta a mesma historia da distribuicao,
        # com outro desenho, e as duas juntas so' faziam a tela pedir rolagem.
        card_hist = Card("Distribuição dos frametimes", theme.GPU)
        self.hist = Histogram(height=150)
        card_hist.add(self.hist, 1)
        lay.addWidget(card_hist, 2)

        bottom = QHBoxLayout()
        bottom.setSpacing(theme.scaled(theme.GAP))
        card_res = Card("Resultado", theme.FPS)
        self.result_rows = MetricList([
            ("game", "Jogo"), ("frames", "Frames"), ("duration", "Duração"),
            ("min", "FPS mínimo"), ("max", "FPS máximo"), ("p1", "Percentil 1"),
            ("ftmax", "Frametime máx"), ("hitches", "Engasgos"),
            ("consistency", "Consistência"), ("bottleneck", "Gargalo"),
        ])
        card_res.add(self.result_rows)
        self.verdict = label("", 8.5, QFont.Weight.Normal, theme.MUTE)
        self.verdict.setWordWrap(True)
        card_res.add(self.verdict)
        bottom.addWidget(card_res, 1)

        card_sys = Card("Sistema durante a corrida", theme.CPU, "média / máximo")
        self.sys_rows = MetricList([
            ("cpu", "CPU"), ("cpu_temp", "CPU temp"), ("cpu_watts", "CPU potência"),
            ("gpu", "GPU"), ("gpu_temp", "GPU temp"), ("gpu_watts", "GPU potência"),
            ("ram", "RAM"), ("vram", "VRAM"),
        ])
        card_sys.add(self.sys_rows)
        card_sys.body.addStretch(1)
        bottom.addWidget(card_sys, 1)

        # "Corridas anteriores" saiu daqui: virou caso particular da tabela de
        # sessoes, que ja' guarda o historico e ainda deixa exportar.
        lay.addLayout(bottom, 2)

        # Relatorio corrido: os cards de cima mostram cada numero no seu lugar,
        # mas na hora de comparar com alguem, ou de guardar, o que serve e' o
        # texto inteiro num bloco so'.
        card_rel = Card("Relatório da corrida", theme.accent_color(self.cfg.accent),
                        "tudo o que foi observado no período")
        self.relatorio = QPlainTextEdit()
        self.relatorio.setReadOnly(True)
        self.relatorio.setMinimumHeight(theme.scaled(210))
        self.relatorio.setFont(QFont(theme.FONT_MONO if hasattr(theme, "FONT_MONO")
                                     else theme.FONT_UI, max(7, theme.scaled(9))))
        card_rel.add(self.relatorio, 1)
        linha = QHBoxLayout()
        linha.setSpacing(theme.scaled(8))
        self.btn_copiar = PillButton("Copiar relatório", theme.accent_color(self.cfg.accent))
        self.btn_copiar.clicked.connect(self._copiar)
        linha.addWidget(self.btn_copiar)
        linha.addStretch(1)
        card_rel.add_layout(linha)
        lay.addWidget(card_rel, 2)

        lay.addStretch(0)
        self._fill_sessoes()

    def _fill_sessoes(self) -> None:
        """Redesenha a tabela de sessoes, da mais recente para a mais antiga."""
        self._sessoes = list(reversed(getattr(self.app, "session_history", [])))
        self.tabela.blockSignals(True)
        self.tabela.setRowCount(len(self._sessoes))
        for linha, s in enumerate(self._sessoes):
            for coluna, texto in enumerate(_celulas(s)):
                item = QTableWidgetItem(texto)
                if coluna:
                    item.setTextAlignment(int(Qt.AlignmentFlag.AlignRight
                                              | Qt.AlignmentFlag.AlignVCenter))
                self.tabela.setItem(linha, coluna, item)
        self.tabela.blockSignals(False)
        self.tabela.resizeColumnsToContents()
        vazio = not self._sessoes
        self.btn_exp_sessao.setVisible(not vazio)
        self.btn_exp_todas.setVisible(not vazio)
        if vazio:
            self.aviso_sessao.setText("Abra um jogo pelos Atalhos com "
                                      "“gravar métricas da partida” ligado.")
        else:
            self.aviso_sessao.setText("")

    def _sessao_atual(self) -> dict | None:
        linhas = self.tabela.selectionModel().selectedRows() if self.tabela.rowCount() else []
        if not linhas:
            return None
        indice = linhas[0].row()
        return self._sessoes[indice] if 0 <= indice < len(self._sessoes) else None

    def _sessao_escolhida(self) -> None:
        """Mostra a sessao escolhida nos cards de resultado.

        A partida nao guarda frame a frame — sao horas de jogo, e caberia em
        centenas de megabytes —, entao os graficos de frametime continuam sendo
        da corrida cronometrada. O que a sessao tem sao os numeros, e e' isso que
        aparece aqui.
        """
        s = self._sessao_atual()
        if s is None:
            return
        self.kpi.set("avg", units.integer(s.get("fps_avg")),
                     theme.fps_color(s.get("fps_avg")))
        self.kpi.set("low1", units.integer(s.get("low_1")),
                     theme.fps_color(s.get("low_1")))
        self.kpi.set("ft", f"{s.get('ft_avg', 0):.2f}", theme.frametime_color(s.get("ft_avg")))
        self.kpi.set("stutter", f"{s.get('stutter_pct', 0):.1f}",
                     theme.stutter_color(s.get("stutter_pct")))
        self.result_rows.set("game", s.get("game", "—"))
        self.result_rows.set("frames", str(s.get("frames", 0)))
        self.result_rows.set("duration", units.duration(s.get("duracao_s")))
        self.result_rows.set("min", units.integer(s.get("fps_min")))
        self.result_rows.set("max", units.integer(s.get("fps_max")))
        self.result_rows.set("p1", units.integer(s.get("low_1")))
        self.result_rows.set("ftmax", units.ms(s.get("ft_max"), 2))
        self.result_rows.set("hitches", str(s.get("hitches", 0)),
                             theme.BAD if s.get("hitches") else theme.OK)
        self.relatorio.setPlainText(_texto_sessao(s))

    def _exportar_sessao(self) -> None:
        s = self._sessao_atual()
        if s is None:
            self.aviso_sessao.setText("Escolha uma sessão na lista primeiro.")
            return
        self._salvar([s], s.get("game", "sessao"))

    def _exportar_sessoes(self) -> None:
        if self._sessoes:
            self._salvar(self._sessoes, "sessoes")

    def _salvar(self, linhas: list[dict], nome: str) -> None:
        try:
            caminho = export.export_sessions(linhas, nome)
        except Exception as e:                                   # noqa: BLE001
            self.aviso_sessao.setText(f"Não consegui salvar: {e}")
            return
        self.aviso_sessao.setText(f"Salvo em {caminho}")

    def on_activate(self) -> None:
        self._fill_sessoes()

    def _copiar(self) -> None:
        from PySide6.QtWidgets import QApplication
        QApplication.clipboard().setText(self.relatorio.toPlainText())
        self.btn_copiar.setText("Copiado!")
        QTimer.singleShot(1600, lambda: self.btn_copiar.setText("Copiar relatório"))

    # ── acoes ────────────────────────────────────────────────────────────────
    def _toggle(self) -> None:
        if self.app.benchmark_active():
            self.app.benchmark_stop()
        else:
            self.app.benchmark_start(self.cfg.bench_seconds)

    def _pick_duration(self) -> None:
        menu = QMenu(self)
        for seconds in (15, 30, 60, 120, 300, 600):
            menu.addAction(f"{seconds} s", lambda s=seconds: self._set_duration(s))
        menu.addSeparator()
        menu.addAction("Manual (parar no botão)", lambda: self._set_duration(3600))
        menu.exec(self.dur_btn.mapToGlobal(QPoint(0, self.dur_btn.height() + 4)))

    def _set_duration(self, seconds: int) -> None:
        self.cfg.bench_seconds = seconds
        self.app.save_settings()
        self.dur_btn.setText("Duração: manual" if seconds >= 3600 else f"Duração: {seconds}s")

    def _export(self) -> None:
        path = self.app.benchmark_export()
        if path:
            self.app.notify("DBX Stats", f"Benchmark exportado para {path.name}")
        else:
            self.app.notify("DBX Stats", "Nenhum benchmark para exportar.")

    def on_settings_changed(self) -> None:
        self.run_btn.set_color(theme.accent_color(self.cfg.accent))
        self.ft_chart.configure(self.cfg.smooth_lines)

    def on_fps(self) -> None:
        state = self.app.benchmark_state()
        if state["active"]:
            self.run_btn.setText("Parar benchmark")
            self.run_btn.set_color(theme.BAD)
            ratio = min(1.0, state["elapsed"] / max(1.0, state["total"]))
            self.progress.setValue(int(ratio * 1000))
            self.target.update_badge(
                f"{state['game']} · {state['frames']} frames · "
                f"{state['elapsed']:.0f}/{state['total']:.0f}s", theme.FPS)
        else:
            self.run_btn.setText("Iniciar benchmark")
            self.run_btn.set_color(theme.accent_color(self.cfg.accent))
            stream = self.app.active_stream()
            self.target.update_badge(stream.app if stream else "nenhum jogo",
                                     theme.FPS if stream else theme.FAINT)
            if not self.app.benchmark_last():
                self.progress.setValue(0)

        result = self.app.benchmark_last()
        if result is not None and result.get("_rev") != getattr(self, "_rev", None):
            self._rev = result.get("_rev")
            self._show(result)

    # ── resultado ────────────────────────────────────────────────────────────
    def _show(self, result: dict) -> None:
        m: fr.FrameMetrics = result["metrics"]
        ft = result["frametimes"]
        self.progress.setValue(1000)
        self.kpi.set("avg", units.integer(m.fps_avg), theme.fps_color(m.fps_avg))
        self.kpi.set("low1", units.integer(m.low_1), theme.fps_color(m.low_1))
        self.kpi.set("ft", f"{m.ft_avg:.2f}" if m.ft_avg else units.DASH,
                     theme.frametime_color(m.ft_avg))
        self.kpi.set("stutter", f"{m.stutter_pct:.1f}", theme.stutter_color(m.stutter_pct))
        self.kpi.set("smooth", f"{m.smoothness:.0f}" if m.smoothness is not None
                     else units.DASH, theme.score_color(m.smoothness))

        self.ft_chart.set_data(ft)
        centers, counts = fr.histogram(ft)
        self.hist.set_data(centers, counts)

        self.result_rows.set("game", result.get("game", "—"))
        self.result_rows.set("frames", str(m.frames))
        self.result_rows.set("duration", units.duration(m.duration))
        self.result_rows.set("min", units.integer(m.fps_min), theme.fps_color(m.fps_min))
        self.result_rows.set("max", units.integer(m.fps_max))
        self.result_rows.set("p1", units.integer(m.p1))
        self.result_rows.set("ftmax", units.ms(m.ft_max, 2), theme.frametime_color(m.ft_max))
        self.result_rows.set("hitches", str(m.hitches), theme.BAD if m.hitches else theme.OK)
        self.result_rows.set("consistency", f"{m.consistency:.0f}%" if m.consistency
                             is not None else units.DASH, theme.score_color(m.consistency))
        self.result_rows.set("bottleneck", m.bottleneck)
        self.verdict.setText(fr.verdict(m))
        self.relatorio.setPlainText(_texto_relatorio(result))

        env = result.get("system", {})
        for key, unit, decimals in (("cpu", "%", 0), ("cpu_temp", "°C", 0),
                                    ("cpu_watts", " W", 0), ("gpu", "%", 0),
                                    ("gpu_temp", "°C", 0), ("gpu_watts", " W", 0),
                                    ("ram", "%", 0), ("vram", "%", 0)):
            pair = env.get(key)
            if pair:
                self.sys_rows.set(key, f"{pair[0]:.{decimals}f}{unit} / "
                                       f"{pair[1]:.{decimals}f}{unit}")
            else:
                self.sys_rows.set(key, units.DASH)

        self._fill_sessoes()


_COLUNAS_SESSAO = ("Quando", "Jogo", "Duração", "FPS médio", "1% low", "Travadas")


def _celulas(s: dict) -> list[str]:
    minutos = (s.get("duracao_s") or 0) / 60.0
    return [
        str(s.get("quando", "")),
        str(s.get("game", "")),
        f"{minutos:.0f} min",
        f"{s.get('fps_avg', 0):.0f}",
        f"{s.get('low_1', 0):.0f}",
        str(s.get("hitches", 0)),
    ]


def _texto_sessao(s: dict) -> str:
    """Relatorio de uma partida inteira, em texto, pronto para copiar."""
    minutos = (s.get("duracao_s") or 0) / 60.0
    linhas = [f"{s.get('game', 'jogo')} — {s.get('quando', '')}", ""]
    linhas.append(_linha("Duração", f"{minutos:.0f} min"))
    linhas.append(_linha("Frames", str(s.get("frames", 0))))
    linhas.append(_linha("FPS médio", f"{s.get('fps_avg', 0):.1f}"))
    linhas.append(_linha("FPS mínimo", f"{s.get('fps_min', 0):.1f}"))
    linhas.append(_linha("FPS máximo", f"{s.get('fps_max', 0):.1f}"))
    linhas.append(_linha("1% low", f"{s.get('low_1', 0):.1f}"))
    linhas.append(_linha("Frametime médio", f"{s.get('ft_avg', 0):.2f} ms"))
    linhas.append(_linha("Frametime máximo", f"{s.get('ft_max', 0):.2f} ms"))
    linhas.append(_linha("Travadas", str(s.get("hitches", 0))))
    linhas.append(_linha("Engasgos", f"{s.get('stutters', 0)} "
                                     f"({s.get('stutter_pct', 0):.2f}%)"))
    sistema = [(k, r) for k, r in (("cpu", "CPU"), ("cpu_temp", "CPU temp"),
                                   ("cpu_watts", "CPU potência"), ("gpu", "GPU"),
                                   ("gpu_temp", "GPU temp"), ("gpu_watts", "GPU potência"),
                                   ("ram", "RAM"), ("vram", "VRAM")) if s.get(k) is not None]
    if sistema:
        linhas.append("")
        linhas.append("Média do sistema durante a partida")
        for chave, rotulo in sistema:
            linhas.append(_linha(rotulo, str(s[chave])))
    return "\n".join(linhas)


def _linha(rotulo: str, valor: str) -> str:
    return f"  {rotulo:<22}{valor}"


def _texto_relatorio(result: dict) -> str:
    """Relatorio legivel de uma corrida inteira.

    Pensado para ser copiado e colado: e' o formato que serve para comparar com
    outra maquina, ou para guardar antes de mexer em alguma configuracao.
    """
    m = result["metrics"]
    sistema = result.get("system") or {}
    linhas = [
        "DBX STATUS — relatório de benchmark",
        f"  jogo: {result.get('game') or '—'}",
    ]
    if result.get("quando"):
        linhas.append(f"  quando: {result['quando']}")
    linhas += [
        "",
        "DESEMPENHO",
        _linha("FPS médio", units.integer(m.fps_avg)),
        _linha("1% low", units.integer(m.low_1)),
        _linha("FPS mínimo / máximo", f"{units.integer(m.fps_min)} / {units.integer(m.fps_max)}"),
        _linha("percentil 1", units.integer(m.p1)),
        "",
        "ENTREGA DE QUADROS",
        _linha("frames", f"{m.frames}"),
        _linha("duração", units.duration(m.duration)),
        _linha("frametime médio", units.ms(m.ft_avg, 2)),
        _linha("frametime máximo", units.ms(m.ft_max, 2)),
        _linha("desvio padrão", units.ms(m.ft_std, 2)),
        _linha("stutter", f"{m.stutter_pct:.2f}%"),
        _linha("engasgos (>50 ms)", f"{m.hitches}"),
        _linha("quadros descartados", f"{m.dropped_pct:.2f}%"),
        _linha("consistência", f"{m.consistency:.0f}%" if m.consistency is not None else "—"),
        _linha("fluidez", f"{m.smoothness:.0f}/100" if m.smoothness is not None else "—"),
        _linha("gargalo", m.bottleneck),
    ]
    if sistema:
        linhas += ["", "SISTEMA NO PERÍODO (média / máximo)"]
        rotulos = {
            "cpu": ("CPU", "%"), "cpu_temp": ("CPU temp", " °C"),
            "cpu_watts": ("CPU potência", " W"), "gpu": ("GPU", "%"),
            "gpu_temp": ("GPU temp", " °C"), "gpu_watts": ("GPU potência", " W"),
            "ram": ("RAM", "%"), "vram": ("VRAM", "%"),
        }
        for chave, (rotulo, unidade) in rotulos.items():
            faixa = sistema.get(chave)
            if not faixa:
                continue
            linhas.append(_linha(rotulo, f"{faixa[0]:.0f}{unidade} / {faixa[1]:.0f}{unidade}"))
    linhas += ["", "LEITURA", "  " + fr.verdict(m)]
    return "\n".join(linhas)
