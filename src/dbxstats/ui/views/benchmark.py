"""Tela de benchmark: captura uma corrida, resume e exporta."""
from __future__ import annotations

from PySide6.QtCore import QPoint, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QMenu,
    QPlainTextEdit,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)

from ... import theme
from ...core import export, units
from ...core import frames as fr
from ..charts import FrameTimeChart, Histogram
from ..confirm import confirmar
from ..components import Badge, Card, KpiStrip, MetricList, PillButton, label
from .base import View, scroll_page

_KPIS = [
    ("avg", "FPS médio", ""), ("low1", "1% Low", ""),
    ("ft", "Frametime", "ms"), ("stutter", "Stutter", "%"), ("smooth", "Fluidez", ""),
]


class SessaoCard(QFrame):
    """Uma partida na lista: capa, jogo, quando, e os numeros que decidem.

    Substitui a linha de tabela. Numa tabela todas as partidas tem o mesmo peso
    visual e o jogo e' uma palavra no meio de seis colunas — para achar "aquela
    vez que o Palworld travou" era preciso ler linha por linha. Com a capa e os
    numeros grandes, a lista se percorre de relance.
    """

    escolhida = Signal(dict)

    LARGURA_CAPA = 92
    ALTURA_CAPA = 52

    def __init__(self, sessao: dict, itens=None, parent=None) -> None:
        super().__init__(parent)
        self.sessao = sessao
        self._ativa = False
        self.setObjectName("SessaoCard")
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        raiz = QHBoxLayout(self)
        raiz.setContentsMargins(*(theme.scaled(8),) * 4)
        raiz.setSpacing(theme.scaled(10))

        self._capa = self._carregar_capa(sessao.get("game", ""), itens)
        raiz.addWidget(_Miniatura(self._capa, self.LARGURA_CAPA, self.ALTURA_CAPA), 0)

        col = QVBoxLayout()
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(theme.scaled(2))
        topo = QHBoxLayout()
        topo.setSpacing(theme.scaled(6))
        topo.addWidget(label(sessao.get("game", "jogo"), 9.5, QFont.Weight.DemiBold))
        topo.addStretch(1)
        topo.addWidget(label(str(sessao.get("quando", "")), 7.5, color=theme.FAINT))
        col.addLayout(topo)

        numeros = QHBoxLayout()
        numeros.setSpacing(theme.scaled(12))
        for valor, rotulo, cor in self._destaques(sessao):
            caixa = QVBoxLayout()
            caixa.setSpacing(0)
            caixa.addWidget(label(valor, 10.5, QFont.Weight.Bold, cor))
            caixa.addWidget(label(rotulo, 7, color=theme.FAINT))
            numeros.addLayout(caixa)
        numeros.addStretch(1)
        col.addLayout(numeros)
        raiz.addLayout(col, 1)
        self._pintar()

    @staticmethod
    def _destaques(s: dict) -> list[tuple[str, str, str]]:
        """Os quatro numeros que fazem escolher uma partida em vez de outra."""
        return [
            (units.integer(s.get("fps_avg")), "fps médio", theme.fps_color(s.get("fps_avg"))),
            (units.integer(s.get("low_1")), "1% low", theme.fps_color(s.get("low_1"))),
            (f"{float(s.get('stutter_pct') or 0):.1f}%", "engasgo",
             theme.stutter_color(s.get("stutter_pct"))),
            (units.duration(s.get("duracao_s")), "duração", theme.MUTE),
        ]

    @staticmethod
    def _carregar_capa(nome: str, itens):
        """Capa pelo NOME do jogo, e nao pelo caminho.

        A sessao guarda so' o nome; o caminho vive no atalho. A lista de atalhos
        vem de fora justamente para nao reler o settings.json uma vez por card.
        """
        from ...platform import art

        try:
            return art.artwork_by_name(nome, itens)
        except OSError:
            return None

    def set_ativa(self, ativa: bool) -> None:
        if ativa != self._ativa:
            self._ativa = ativa
            self._pintar()

    def _pintar(self) -> None:
        borda = theme.FPS if self._ativa else theme.LINE
        fundo = theme.SURFACE_2 if self._ativa else theme.SURFACE
        self.setStyleSheet(
            f"#SessaoCard {{ background: {fundo}; border: 1px solid {borda};"
            f" border-radius: {theme.scaled(9)}px; }}")

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.escolhida.emit(self.sessao)
        event.accept()


class _Miniatura(QWidget):
    """Capa pequena da sessao, ou as iniciais quando o jogo saiu da lista."""

    def __init__(self, caminho, largura: int, altura: int, parent=None) -> None:
        super().__init__(parent)
        self.setFixedSize(theme.scaled(largura), theme.scaled(altura))
        self._pix = QPixmap(str(caminho)) if caminho else QPixmap()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(0, 0, -1, -1)
        raio = theme.scaled(6)
        caminho = QPainterPath()
        caminho.addRoundedRect(QRectF(rect), raio, raio)
        p.fillPath(caminho, QColor(theme.BG_SUNKEN))
        if not self._pix.isNull():
            p.setClipPath(caminho)
            quadrado = abs(self._pix.width() / max(1, self._pix.height()) - 1.0) < 0.15
            if quadrado:
                lado = int(rect.height() * 0.86)
                esc = self._pix.scaled(lado, lado, Qt.AspectRatioMode.KeepAspectRatio,
                                       Qt.TransformationMode.SmoothTransformation)
            else:
                esc = self._pix.scaled(rect.size(),
                                       Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                       Qt.TransformationMode.SmoothTransformation)
            p.drawPixmap(rect.x() + (rect.width() - esc.width()) // 2,
                         rect.y() + (rect.height() - esc.height()) // 2, esc)
        p.end()


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

        # Duas colunas: a esquerda e' a biblioteca de partidas, a direita e' a
        # partida escolhida. Empilhado em coluna unica, o Resultado e o Relatorio
        # ficavam abaixo da dobra — existiam, mas ninguem via.
        colunas = QHBoxLayout()
        colunas.setSpacing(theme.scaled(theme.GAP))
        root.addLayout(colunas, 1)

        self.card_sessoes = Card("Sessões de jogo", theme.FPS,
                                 "gravadas do início ao fim ao abrir pela aba Jogos")
        lista_page, self.lista_box = scroll_page()
        self.lista_box.setSpacing(theme.scaled(6))
        self.card_sessoes.add(lista_page, 1)

        acoes = QHBoxLayout()
        acoes.setSpacing(theme.scaled(8))
        self.btn_del_sessao = PillButton("Excluir esta", theme.BAD)
        self.btn_del_sessao.clicked.connect(self._excluir_sessao)
        self.btn_del_todas = PillButton("Excluir todas", theme.BAD)
        self.btn_del_todas.clicked.connect(self._excluir_todas)
        self.btn_exp_sessao = PillButton("Exportar esta sessão", theme.MUTE)
        self.btn_exp_sessao.clicked.connect(self._exportar_sessao)
        self.btn_exp_todas = PillButton("Exportar todas", theme.MUTE)
        self.btn_exp_todas.clicked.connect(self._exportar_sessoes)
        acoes.addWidget(self.btn_exp_sessao)
        acoes.addWidget(self.btn_del_sessao)
        acoes.addWidget(self.btn_del_todas)
        acoes.addWidget(self.btn_exp_todas)
        acoes.addStretch(1)
        self.aviso_sessao = label("", 8.5, color=theme.MUTE)
        acoes.addWidget(self.aviso_sessao)
        self.card_sessoes.add_layout(acoes)

        esquerda = QVBoxLayout()
        esquerda.setSpacing(theme.scaled(theme.GAP))
        esquerda.addWidget(self.card_sessoes, 1)
        colunas.addLayout(esquerda, 4)

        page, lay = scroll_page()
        colunas.addWidget(page, 6)

        self.card_ft = Card("Frametime da corrida", theme.FRAME)
        self.ft_chart = FrameTimeChart(height=200)
        self.card_ft.add(self.ft_chart, 1)
        self.card_ft.setVisible(False)
        lay.addWidget(self.card_ft, 3)

        # A curva de percentis saiu: ela conta a mesma historia da distribuicao,
        # com outro desenho, e as duas juntas so' faziam a tela pedir rolagem.
        self.card_hist = Card("Distribuição dos frametimes", theme.GPU)
        self.hist = Histogram(height=150)
        self.card_hist.add(self.hist, 1)
        lay.addWidget(self.card_hist, 2)

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
        """Redesenha a lista de partidas, da mais recente para a mais antiga."""
        self._sessoes = list(reversed(getattr(self.app, "session_history", [])))
        escolhida = getattr(self, "_escolhida", None)

        while self.lista_box.count():
            item = self.lista_box.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()

        itens = list(getattr(self.cfg, "launch_items", []) or [])
        self._cards: list[SessaoCard] = []
        for s in self._sessoes:
            card = SessaoCard(s, itens)
            card.escolhida.connect(self._escolher)
            self.lista_box.addWidget(card)
            self._cards.append(card)
        self.lista_box.addStretch(1)

        # A escolha sobrevive ao redesenho enquanto a partida existir: apagar
        # uma sessao nao pode mudar qual das outras estava aberta a' direita.
        if escolhida not in self._sessoes:
            escolhida = None
        self._escolhida = escolhida
        self._marcar_ativo()

        vazio = not self._sessoes
        self.btn_exp_sessao.setVisible(not vazio)
        self.btn_del_sessao.setVisible(not vazio)
        self.btn_del_todas.setVisible(not vazio)
        self.btn_exp_todas.setVisible(not vazio)
        if vazio:
            self.aviso_sessao.setText("Abra um jogo pela aba Jogos com "
                                      "“gravar métricas da partida” ligado.")
        else:
            self.aviso_sessao.setText("")

    def _escolher(self, sessao: dict) -> None:
        self._escolhida = sessao
        self._marcar_ativo()
        self._sessao_escolhida()

    def _marcar_ativo(self) -> None:
        for card in getattr(self, "_cards", []):
            card.set_ativa(card.sessao is self._escolhida)

    def _sessao_atual(self) -> dict | None:
        return getattr(self, "_escolhida", None)

    def _sessao_escolhida(self) -> None:
        """Mostra a sessao escolhida nos cards de resultado.

        A partida nao guarda frame a frame — sao horas de jogo, e caberia em
        centenas de megabytes —, entao os graficos de frametime continuam sendo
        da corrida cronometrada. O que a sessao tem sao os numeros, e e' isso que
        aparece aqui.
        """
        s = self._sessao_atual()
        if s is None:
            # Nada escolhido: os paineis tem de esvaziar junto. Deixar a ultima
            # sessao ali depois de apagar ela da lista mostra numeros de uma
            # partida que nao existe mais, e nao ha' nada na tela dizendo isso.
            self._limpar_resultado()
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
        self._graficos_da_sessao(s)

    def _limpar_resultado(self) -> None:
        """Zera tudo que descreve uma partida: KPIs, tabelas, graficos e texto.

        Um painel so' esquecido ja' basta para enganar — o card de Resultado
        continuava dizendo "Palworld, 138820 frames" com a lista vazia.
        """
        for chave in ("avg", "low1", "ft", "stutter", "smooth"):
            self.kpi.set(chave, units.DASH, theme.FAINT)
        for chave in ("game", "frames", "duration", "min", "max", "p1",
                      "ftmax", "hitches", "consistency", "bottleneck"):
            self.result_rows.set(chave, units.DASH, theme.FAINT)
        for chave in ("cpu", "cpu_temp", "cpu_watts", "gpu", "gpu_temp",
                      "gpu_watts", "ram", "vram"):
            self.sys_rows.set(chave, units.DASH)
        self.verdict.setText("")
        self.relatorio.setPlainText("")
        self.ft_chart.set_data([])
        self.hist.set_data([], [])
        self.card_ft.setVisible(False)
        self.card_hist.set_hint("", theme.FAINT)

    def _graficos_da_sessao(self, s: dict) -> None:
        """Desenha o que a partida guardou, e diz o que ela nao guardou.

        A distribuicao sai do histograma gravado junto com a sessao. A curva de
        frametime nao existe: seriam milhoes de amostras por partida, e o
        gravador e' de memoria constante justamente para nao mante-las. Antes os
        dois graficos ficavam com a corrida cronometrada anterior na tela, e a
        leitura obvia era que a sessao escolhida tinha aqueles numeros.
        """
        hist = s.get("hist") or {}
        contagens = hist.get("c") or []
        if contagens:
            largura = float(hist.get("w", 0.1))
            inicio = int(hist.get("i0", 0)) * 0.1
            centros = [inicio + (i + 0.5) * largura for i in range(len(contagens))]
            self.hist.set_data(centros, list(contagens))
        else:
            # Sessao gravada antes desta versao: nao tem histograma nenhum.
            self.hist.set_data([], [])

        # O card sai da tela em vez de mostrar um grafico vazio dizendo
        # "aguardando frames do jogo": nao ha' nada a aguardar, a partida
        # simplesmente nunca teve essa curva. Grafico vazio le' como travado.
        self.ft_chart.set_data([])
        self.card_ft.setVisible(False)
        self.card_hist.set_hint(
            "" if contagens else "esta sessão foi gravada antes deste gráfico existir",
            theme.FAINT)

    def _excluir_sessao(self) -> None:
        """Apaga a partida escolhida.

        Sem confirmacao: e' UMA linha, o usuario acabou de escolher ela na lista,
        e o estrago cabe numa frase. Pedir "tem certeza?" para cada exclusao de
        item unico so' ensina a clicar em sim sem ler.
        """
        s = self._sessao_atual()
        if s is None:
            self.aviso_sessao.setText("Escolha uma sessão na lista primeiro.")
            return
        historico = getattr(self.app, "session_history", None)
        if historico is None:
            return
        try:
            historico.remove(s)
        except ValueError:
            return
        self._escolhida = None
        self._salvar_historico()
        nome = s.get("game", "sessão")
        self.aviso_sessao.setText(f"'{nome}' removida.")

    def _excluir_todas(self) -> None:
        """Apaga o historico inteiro — este sim pergunta antes.

        Aqui o estrago e' de todas as partidas ja' gravadas, e nao ha' desfazer:
        o arquivo e' reescrito na hora.
        """
        historico = getattr(self.app, "session_history", None)
        if not historico:
            return
        quantas = len(historico)
        if not confirmar("Excluir todas as sessões?",
                         f"As {quantas} partidas gravadas serão apagadas. "
                         "Não dá para desfazer.",
                         rotulo_ok="Excluir tudo", perigo=True, parent=self):
            return
        historico.clear()
        self._escolhida = None
        self._salvar_historico()
        self.aviso_sessao.setText(f"{quantas} sessões apagadas.")

    def _salvar_historico(self) -> None:
        """Grava o historico, redesenha a tabela e esvazia o que ficou orfao.

        A limpeza mora aqui, e nao em `_fill_sessoes`, porque aquele metodo
        tambem roda quando uma partida ACABA de ser gravada — limpar la' apagaria
        da tela o resultado que o usuario acabou de produzir.

        `_fill_sessoes` bloqueia os sinais da tabela enquanto a redesenha, entao
        `itemSelectionChanged` nao dispara e ninguem mais avisaria que a sessao
        que estava aberta nos paineis deixou de existir.
        """
        salvar = getattr(self.app, "save_session_history", None)
        if callable(salvar):
            salvar()
        self._fill_sessoes()
        if self._sessao_atual() is None:
            self._limpar_resultado()

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

        # A corrida cronometrada E' quadro a quadro: aqui o card faz sentido.
        self.card_ft.setVisible(True)
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
