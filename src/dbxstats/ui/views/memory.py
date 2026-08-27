"""Tela de memoria e armazenamento: RAM, swap, unidades, saude, I/O e benchmark."""
from __future__ import annotations

import threading

from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication,
    QGridLayout,
    QHBoxLayout,
    QMenu,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)

from ... import config, theme
from ...core import units
from ...platform import memclean
from ...sensors import diskbench, diskhealth
from ..charts import BarMeter, Plot, Sparkline, TimeSeriesChart
from ..components import Badge, Card, KpiStrip, MetricList, PillButton, dimm_color, label
from ..components import linha_opcional as _linha
from .base import View, scroll_page

_KPIS = [
    ("used", "Em uso", "GB"), ("pct", "Ocupação", "%"), ("avail", "Disponível", "GB"),
    ("freq", "Frequência", "MHz"), ("temp", "Temperatura", "°C"), ("swap", "Swap", "GB"),
    ("disk", "Disco do sistema", "%"),
]

_MAX_DIMMS = 8
"""Teto de linhas por pente. Placa de consumo tem 2 ou 4 slots; o dobro cobre HEDT
sem transformar o card numa lista rolante se algum SPD vier repetido."""

# Uma leitura por linha, e rotulo curto. Duas medidas na mesma linha (ou rotulo
# comprido) viram largura minima do card, e ai' a coluna vizinha sai da tela numa
# janela estreita — a tela nao rola na horizontal.
_SAUDE_ROWS = [
    ("life", "Vida restante"), ("written", "Total escrito"), ("read", "Total lido"),
    ("hours", "Ligado há"), ("temp", "Temperatura"), ("temp_max", "Temp. máxima"),
    ("errors_read", "Erros de leitura"), ("errors_write", "Erros de escrita"),
    ("errors", "Erros"), ("spare", "Reserva"), ("cycles", "Ciclos"),
]

_BENCH_ROWS = [
    ("wseq", "Escrita seq."), ("rseq", "Leitura seq."),
    ("ralea", "Leitura 4K"), ("walea", "Escrita 4K"),
    ("iops", "IOPS 4K"), ("arquivo", "Arquivo"),
]

_EXPLICA_LIMPEZA = (
    "Tira da RAM as páginas residentes dos processos e descarta a lista de standby "
    "(o cache de arquivos do Windows). O número de memória disponível sobe, mas isso "
    "não é ganho de desempenho: a standby já estava disponível para quem pedisse, e "
    "logo depois da limpeza o sistema fica mais lento por alguns instantes, porque "
    "precisa reler do disco o que foi descartado. Útil antes de medir consumo do zero, "
    "não durante um jogo."
)

_EXPLICA_BENCH = (
    "Grava um arquivo temporário na própria unidade, mede, e apaga ao terminar — "
    "inclusive se o teste falhar ou o app fechar no meio. Nenhum arquivo existente é "
    "tocado. O acesso é feito sem o cache do sistema, por isso os números são os do "
    "dispositivo e não os da RAM."
)

_EXPLICA_TAMANHO = (
    "Arquivo pequeno (256–512 MiB) cabe no cache SLC do SSD e é reescrito várias "
    "vezes dentro da fase: a escrita sai inflada, é a velocidade do cache e não a do "
    "disco — inclusive num SSD que já está lento por ter escrito muito. Arquivo "
    "grande, com mais tempo por fase, empurra mais gigabytes de uma vez e chega perto "
    "da escrita sustentada, a que aparece ao copiar um jogo inteiro; em SSD com cache "
    "folgado só dá para ver a queda com 4 GiB e 6 s por fase. Arquivo maior também "
    "exige mais espaço livre, e o teste é recusado se não houver."
)

_EXPLICA_FILA = (
    "Fila 1: uma operação por vez, cada uma esperando a anterior — é o que um jogo "
    "carregando textura faz. Fila maior exigiria I/O assíncrono de verdade "
    "(OVERLAPPED), que este motor não usa; oferecer QD32 aqui seria um QD1 com "
    "rótulo errado, então só QD1 é oferecido."
)

_EXPLICA_SO_LEITURA = (
    "Só leitura marcada: o arquivo é gravado antes, na fase “preparando”, e essa "
    "gravação fica fora da medição — não dá para ler o que não existe."
)


class MemoryView(View):
    key = "memory"
    title = "Memória & Disco"
    glyph = "▤"

    def __init__(self, app) -> None:
        super().__init__(app)
        self._bench = diskbench.DiskBench()
        self._probe = diskhealth.ReliabilityProbe()
        self._probe_liberado = False
        self._mounts: list[str] = []
        # Estado proprio em vez de perguntar ao botao: `isVisible()` e' False
        # quando a tela nao e' a que esta' na frente, e trocar de aba no meio do
        # teste faria o resultado nunca aparecer.
        self._bench_rodando = False
        self._limpeza: threading.Thread | None = None
        self._limpeza_resultado: memclean.Resultado | None = None
        self._limpeza_erro = ""

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
            ("avail", "Disponível"), ("jogo", "Jogo em foco"),
            ("jogo_ws", "Residente do jogo"), ("swap", "Arquivo de paginação"),
            ("modules", "Módulos"), ("temp", "Pente mais quente"),
        ])
        card_ram.add(self.ram_rows)
        # Uma linha por pente, criada uma vez e escondida enquanto nao ha' leitura:
        # a temperatura dos modulos so' existe com o app elevado, e o numero de
        # pentes muda de maquina para maquina.
        self.mod_rows = MetricList([(f"m{i}", "") for i in range(_MAX_DIMMS)])
        card_ram.add(self.mod_rows)
        for i in range(_MAX_DIMMS):
            self.mod_rows.row(f"m{i}").setVisible(False)
        card_ram.add_layout(self._montar_limpeza())
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

        baixo = QHBoxLayout()
        baixo.setSpacing(theme.scaled(theme.GAP))
        baixo.addWidget(self._montar_saude(), 3)
        baixo.addWidget(self._montar_bench(), 2)
        lay.addLayout(baixo, 2)
        lay.addStretch(0)

        # Um relogio so' para as duas tarefas em thread. Fica parado enquanto nao
        # ha' nada rodando, entao a tela nao paga nada por existir.
        self._timer = QTimer(self)
        self._timer.setInterval(200)
        self._timer.timeout.connect(self._tick_tarefas)

        qt = QApplication.instance()
        if qt is not None:
            # Fechar o app com um teste rodando deixaria a thread escrevendo e o
            # arquivo de 1 GB na unidade; cancelar aqui fecha o handle e o
            # Windows apaga o arquivo sozinho (FILE_FLAG_DELETE_ON_CLOSE).
            qt.aboutToQuit.connect(self._encerrar)

    def _montar_limpeza(self) -> QVBoxLayout:
        box = QVBoxLayout()
        box.setSpacing(theme.scaled(5))
        linha = QHBoxLayout()
        linha.setSpacing(theme.scaled(8))
        self.btn_limpar = PillButton("Liberar memória", theme.RAM)
        self.btn_limpar.setToolTip("Esvazia working sets e descarta a lista de standby")
        self.btn_limpar.clicked.connect(self._limpar_memoria)
        linha.addWidget(self.btn_limpar)
        linha.addStretch(1)
        box.addLayout(linha)
        # O resumo fica em linha propria e com quebra: ao lado do botao, uma
        # frase longa vira largura minima do card e empurra o vizinho para fora
        # da tela — foi assim que a linha de cima quebrou no primeiro desenho.
        self.limpeza_status = label("", 8, QFont.Weight.DemiBold, theme.FAINT)
        self.limpeza_status.setWordWrap(True)
        box.addWidget(self.limpeza_status)
        aviso = label(_EXPLICA_LIMPEZA, 7.5, QFont.Weight.Normal, theme.FAINT)
        aviso.setWordWrap(True)
        box.addWidget(aviso)
        return box

    def _montar_saude(self) -> Card:
        self.card_saude = Card("Saúde das unidades", theme.DISK, "SMART / NVMe")
        self.saude_aviso = label("Lendo a saúde dos discos…", 8.5,
                                 QFont.Weight.Normal, theme.FAINT)
        self.saude_aviso.setWordWrap(True)
        self.card_saude.add(self.saude_aviso)
        self.saude_grid = QGridLayout()
        self.saude_grid.setSpacing(theme.scaled(theme.GAP))
        self.card_saude.add_layout(self.saude_grid)
        self.card_saude.body.addStretch(1)
        self._saude_widgets: list[dict] = []
        return self.card_saude

    def _montar_bench(self) -> Card:
        self.card_bench = Card("Velocidade das unidades", theme.GPU, "sem cache")
        linha = QHBoxLayout()
        linha.setSpacing(theme.scaled(8))
        self.btn_testar = PillButton("Testar unidade", theme.GPU, filled=True)
        self.btn_testar.clicked.connect(self._iniciar_bench)
        linha.addWidget(self.btn_testar)
        self.btn_cancelar = PillButton("Cancelar", theme.BAD)
        self.btn_cancelar.clicked.connect(self._cancelar_bench)
        self.btn_cancelar.setVisible(False)
        linha.addWidget(self.btn_cancelar)
        linha.addStretch(1)
        self.bench_badge = Badge("parado", theme.FAINT)
        linha.addWidget(self.bench_badge)
        self.card_bench.add_layout(linha)
        self.card_bench.add_layout(self._montar_opcoes_bench())

        self.bench_progress = QProgressBar()
        self.bench_progress.setTextVisible(False)
        self.bench_progress.setFixedHeight(theme.scaled(6))
        self.bench_progress.setRange(0, 1000)
        self.bench_progress.setValue(0)
        self.card_bench.add(self.bench_progress)

        self.bench_rows = MetricList(_BENCH_ROWS)
        self.card_bench.add(self.bench_rows)
        self.bench_aviso = label(_EXPLICA_BENCH, 7.5, QFont.Weight.Normal, theme.FAINT)
        self.bench_aviso.setWordWrap(True)
        self.card_bench.add(self.bench_aviso)
        self.card_bench.body.addStretch(1)
        self._sync_opcoes_bench()
        return self.card_bench

    def _montar_opcoes_bench(self) -> QVBoxLayout:
        """As escolhas do teste, na própria tela: unidade, tamanho, fases, tempo."""
        box = QVBoxLayout()
        box.setSpacing(theme.scaled(5))

        grade = QGridLayout()
        grade.setHorizontalSpacing(theme.scaled(8))
        grade.setVerticalSpacing(theme.scaled(4))
        self.opt_unidade = _Escolha(theme.GPU, self._opcoes_unidade, self._set_unidade)
        self.opt_tamanho = _Escolha(theme.GPU, _opcoes_tamanho, self._set_tamanho)
        self.opt_tamanho.setToolTip(_EXPLICA_TAMANHO)
        self.opt_tempo = _Escolha(theme.GPU, _opcoes_tempo, self._set_tempo)
        self.opt_tempo.setToolTip("Tempo mínimo de medição de cada fase. Mais tempo, "
                                  "número mais estável; menos tempo, teste mais rápido.")
        fila = label(f"QD{diskbench.PROFUNDIDADES[0]}", 8.5,
                     QFont.Weight.DemiBold, theme.MUTE)
        fila.setToolTip(_EXPLICA_FILA)
        esquerda = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        for i, (texto, widget) in enumerate((("Unidade", self.opt_unidade),
                                             ("Arquivo", self.opt_tamanho),
                                             ("Tempo/fase", self.opt_tempo),
                                             ("Fila", fila))):
            rotulo = label(texto, 7.5, QFont.Weight.Normal, theme.FAINT)
            grade.addWidget(rotulo, i // 2, (i % 2) * 2, esquerda)
            grade.addWidget(widget, i // 2, (i % 2) * 2 + 1, esquerda)
        # A folga vai toda para a coluna vazia da direita: esticar a coluna da
        # pilula so' afastaria o valor do rotulo a que ele pertence.
        grade.setColumnStretch(4, 1)
        box.addLayout(grade)

        # Duas colunas em vez de quatro pilulas lado a lado: o card divide a
        # largura com o de saude, e quatro rotulos numa linha so' vazam para fora.
        fases = QGridLayout()
        fases.setHorizontalSpacing(theme.scaled(6))
        fases.setVerticalSpacing(theme.scaled(4))
        self._fase_botoes: dict[str, _FaseToggle] = {}
        for i, (chave, rotulo) in enumerate(config.DISKBENCH_PHASES):
            botao = _FaseToggle(chave, rotulo)
            botao.clicked.connect(lambda c=chave: self._alternar_fase(c))
            self._fase_botoes[chave] = botao
            fases.addWidget(botao, i // 2, i % 2, esquerda)
        fases.setColumnStretch(2, 1)
        box.addLayout(fases)

        self.bench_resumo = label("", 7.5, QFont.Weight.DemiBold, theme.FAINT)
        self.bench_resumo.setWordWrap(True)
        box.addWidget(self.bench_resumo)
        return box

    def on_activate(self) -> None:
        # So' a partir daqui a consulta de saude pode rodar: ela abre um
        # PowerShell, e telas nunca abertas nao tem por que pagar por isso.
        self._probe_liberado = True

    def _encerrar(self) -> None:
        self._timer.stop()
        self._bench.cancelar(esperar=3.0)

    def on_settings_changed(self) -> None:
        for chart in (self.ram_chart, self.io_chart):
            chart.configure(**self.chart_config())
            chart.set_span(self.cfg.history_window)

    def _limpar_memoria(self) -> None:
        """Dispara a limpeza fora da thread da UI.

        Percorrer algumas centenas de processos abrindo handle em cada um leva
        de decimos a segundos; na thread da UI isso apareceria como travada.
        """
        if self._limpeza is not None and self._limpeza.is_alive():
            return
        self._limpeza_resultado = None
        self._limpeza_erro = ""
        self.btn_limpar.setText("Liberando…")
        self.limpeza_status.setText("")
        self._limpeza = threading.Thread(target=self._rodar_limpeza,
                                         name="memclean", daemon=True)
        self._limpeza.start()
        self._timer.start()

    def _rodar_limpeza(self) -> None:
        try:
            self._limpeza_resultado = memclean.limpar()
        except Exception as e:                       # noqa: BLE001
            self._limpeza_erro = f"A limpeza falhou: {type(e).__name__}."

    def _concluir_limpeza(self) -> None:
        self.btn_limpar.setText("Liberar memória")
        if self._limpeza_erro:
            self.limpeza_status.setText(self._limpeza_erro)
            self.limpeza_status.setStyleSheet(f"color: {theme.BAD}; background: transparent;")
            return
        r = self._limpeza_resultado
        if r is None:
            return
        cor = theme.OK if r.standby else theme.WARN
        texto = memclean.resumo(r)
        if not r.standby and r.erro_standby:
            texto = f"{texto} — {r.erro_standby}"
        self.limpeza_status.setText(texto)
        self.limpeza_status.setStyleSheet(f"color: {cor}; background: transparent;")

    def _opcoes_unidade(self) -> list[tuple[str, str]]:
        return [(m, m) for m in (self._mounts or ["C:\\"])]

    def _unidade_bench(self) -> str:
        """A unidade escolhida, ou a primeira que o coletor listou."""
        escolhida = (self.cfg.diskbench_drive or "").strip()
        return escolhida or (self._mounts or ["C:\\"])[0]

    def _guardar(self) -> None:
        """Persiste a escolha. `save_settings` pode nao existir num app de teste."""
        salvar = getattr(self.app, "save_settings", None)
        if callable(salvar):
            salvar()

    def _set_unidade(self, mount: str) -> None:
        self.cfg.diskbench_drive = mount
        self._guardar()
        self._sync_opcoes_bench()

    def _set_tamanho(self, mib: int) -> None:
        self.cfg.diskbench_size_mib = int(mib)
        self._guardar()
        self._sync_opcoes_bench()

    def _set_tempo(self, segundos: float) -> None:
        self.cfg.diskbench_seconds = float(segundos)
        self._guardar()
        self._sync_opcoes_bench()

    def _alternar_fase(self, chave: str) -> None:
        """Marca ou desmarca uma fase, sem nunca deixar o teste sem nenhuma."""
        marcadas = [c for c, _ in config.DISKBENCH_PHASES
                    if c in set(self.cfg.diskbench_phases)]
        if chave in marcadas:
            if len(marcadas) == 1:
                return
            marcadas.remove(chave)
        else:
            marcadas = [c for c, _ in config.DISKBENCH_PHASES
                        if c in set(marcadas) | {chave}]
        self.cfg.diskbench_phases = marcadas
        self._guardar()
        self._sync_opcoes_bench()

    def _opcoes_bench(self) -> diskbench.Opcoes:
        return diskbench.Opcoes(
            tamanho=int(self.cfg.diskbench_size_mib) * diskbench.MIB,
            fases=tuple(self.cfg.diskbench_phases),
            segundos_fase=float(self.cfg.diskbench_seconds),
            profundidade=int(self.cfg.diskbench_queue_depth),
        ).normalizar()

    def _sync_opcoes_bench(self) -> None:
        opcoes = self._opcoes_bench()
        self.opt_unidade.mostrar(self._unidade_bench())
        self.opt_tamanho.mostrar(_rotulo_tamanho(self.cfg.diskbench_size_mib))
        self.opt_tempo.mostrar(_rotulo_tempo(self.cfg.diskbench_seconds))
        for chave, botao in self._fase_botoes.items():
            botao.set_ativo(chave in opcoes.fases)
        # A conta do espaco exigido fica visivel porque ela e' o motivo de o teste
        # ser recusado: escolher 4 GiB muda o que a unidade precisa ter livre.
        precisa = units.size(opcoes.tamanho + diskbench.MARGEM_LIVRE)
        resumo = (f"{_rotulo_tamanho(self.cfg.diskbench_size_mib)} · "
                  f"{len(opcoes.fases)} de {len(config.DISKBENCH_PHASES)} fases · "
                  f"{_rotulo_tempo(self.cfg.diskbench_seconds)}/fase · "
                  f"precisa de {precisa} livres")
        if opcoes.precisa_preparar:
            resumo = f"{resumo}\n{_EXPLICA_SO_LEITURA}"
        self.bench_resumo.setText(resumo)

    def _iniciar_bench(self, mount: str | None = None) -> None:
        mount = mount or self._unidade_bench()
        ok, erro = self._bench.iniciar(mount, self._opcoes_bench())
        if not ok:
            self.bench_badge.update_badge("recusado", theme.BAD)
            self.bench_aviso.setText(erro)
            self.bench_aviso.setStyleSheet(f"color: {theme.BAD}; background: transparent;")
            return
        self.bench_aviso.setText(_EXPLICA_BENCH)
        self.bench_aviso.setStyleSheet(f"color: {theme.FAINT}; background: transparent;")
        self._bench_rodando = True
        self.btn_cancelar.setVisible(True)
        self.btn_testar.setText("Testando…")
        self.bench_progress.setValue(0)
        for chave, _ in _BENCH_ROWS:
            self.bench_rows.set(chave, units.DASH, theme.MUTE)
        self._mostrar_linhas_bench(self._opcoes_bench().fases)
        self._timer.start()

    def _cancelar_bench(self) -> None:
        self.bench_badge.update_badge("cancelando", theme.WARN)
        self._bench.cancelar(esperar=0.0)

    def _tick_tarefas(self) -> None:
        """Unico ponto onde o estado das threads vira widget."""
        ocupado = False
        estado = self._bench.estado()
        if estado["ativo"]:
            ocupado = True
            self.bench_badge.update_badge(
                f"{estado['unidade']} · {estado['fase']}", theme.GPU)
            self.bench_progress.setValue(int(estado["progresso"] * 1000))
        elif self._bench_rodando:
            self._bench_rodando = False
            self.btn_cancelar.setVisible(False)
            self.btn_testar.setText("Testar unidade")
            self._mostrar_bench(estado)

        if self._limpeza is not None:
            if self._limpeza.is_alive():
                ocupado = True
            else:
                self._limpeza = None
                self._concluir_limpeza()
        if not ocupado:
            self._timer.stop()

    def _mostrar_linhas_bench(self, fases) -> None:
        """Esconde a linha de fase que nao foi pedida.

        Travessao numa fase desmarcada se le' como "o teste tentou e falhou aqui",
        que e' exatamente o oposto do que aconteceu.
        """
        rodadas = set(fases or ())
        for chave, _rotulo in config.DISKBENCH_PHASES:
            linha = self.bench_rows.row(chave)
            if linha is not None:
                linha.setVisible(chave in rodadas)
        iops = self.bench_rows.row("iops")
        if iops is not None:
            iops.setVisible(bool(rodadas & {"ralea", "walea"}))

    def _mostrar_bench(self, estado: dict) -> None:
        if estado["erro"]:
            self.bench_badge.update_badge("falhou", theme.BAD)
            self.bench_progress.setValue(0)
            self.bench_aviso.setText(estado["erro"])
            self.bench_aviso.setStyleSheet(f"color: {theme.BAD}; background: transparent;")
            return
        r = estado["resultado"]
        if r is None:
            self.bench_badge.update_badge("cancelado", theme.WARN)
            self.bench_progress.setValue(0)
            return
        if r.cancelado:
            self.bench_badge.update_badge("cancelado · parcial", theme.WARN)
            self.bench_progress.setValue(0)
        else:
            self.bench_badge.update_badge(f"{r.unidade} · {r.segundos:.0f}s", theme.OK)
            self.bench_progress.setValue(1000)
        self._mostrar_linhas_bench(r.fases)
        self.bench_rows.set("wseq", units.rate(r.escrita_seq), theme.DISK)
        self.bench_rows.set("rseq", units.rate(r.leitura_seq), theme.GPU)
        self.bench_rows.set("ralea", units.rate(r.leitura_alea), theme.GPU)
        self.bench_rows.set("walea", units.rate(r.escrita_alea), theme.DISK)
        # Com uma das duas fases 4K desmarcada, "10k / —" nao diz qual das duas
        # foi medida; a linha passa a mostrar so' o que rodou, e o rotulo diz o que e'.
        medidos = [(nome, valor) for nome, valor in (("leitura", r.iops_leitura),
                                                     ("escrita", r.iops_escrita)) if valor]
        self.bench_rows.set_label("iops", "IOPS 4K"
                                  + (f" ({'/'.join(n for n, _ in medidos)})"
                                     if len(medidos) == 1 else ""))
        self.bench_rows.set("iops", " / ".join(units.compact(v, 0) for _, v in medidos)
                            or units.DASH)
        self.bench_rows.set("arquivo", f"{units.size(r.bytes_arquivo)}  ·  "
                                       f"QD{r.profundidade}")
        if not r.cache_evitado:
            self.bench_aviso.setText(
                "Esta unidade não aceitou acesso sem cache: os números de leitura "
                "podem estar otimistas porque parte do arquivo veio da RAM.")
            self.bench_aviso.setStyleSheet(f"color: {theme.WARN}; background: transparent;")

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
        temp = d.get("ram_temp")
        self.kpi.set("temp", units.integer(temp), dimm_color(d), "pente mais quente")
        self.kpi.set("swap", f"{d.get('swap_used', 0):.1f}", theme.TXT,
                     f"de {d.get('swap_total', 0):.0f} GB")
        dp = d.get("disk_pct")
        self.kpi.set("disk", units.integer(dp), theme.load_color(dp),
                     f"{d.get('disk_used', 0):.0f} / {d.get('disk_total', 0):.0f} GB")
        # Sem elevacao os pentes nem aparecem na arvore do LHM. O tile some em vez
        # de ficar com travessao fingindo que a maquina nao tem sensor nenhum.
        self.kpi.show_only([k for k, _c, _u in _KPIS if k != "temp" or temp is not None])

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
        # Private bytes primeiro: e' o que o jogo pediu para si e nao colapsa
        # quando o Windows poda o residente num alt-tab. O working set fica logo
        # abaixo porque e' ele quem representa pressao real sobre a RAM fisica.
        _linha(self.ram_rows, "jogo", d.get("game_ram_private"),
               lambda v: units.gib(v / 1024), theme.RAM)
        _linha(self.ram_rows, "jogo_ws", d.get("game_ram_wset"),
               lambda v: units.gib(v / 1024), theme.MUTE)
        self.ram_rows.set_label("jogo", d.get("game_name") or "Jogo em foco")
        self.ram_rows.set("swap", f"{d.get('swap_used', 0):.1f} / "
                                  f"{d.get('swap_total', 0):.0f} GB")
        self.ram_rows.set("modules", f"{info.get('modules', '?')}× {info.get('part', '')}".strip()
                          if info else units.DASH)
        _linha(self.ram_rows, "temp", d.get("ram_temp"), units.temp, dimm_color(d))
        self._sync_modulos(d.get("ram_modules") or [])

        self.io_rows.set("read", units.rate(d.get("disk_r")))
        self.io_rows.set("write", units.rate(d.get("disk_w")))
        self.io_rows.set("total", units.rate((d.get("disk_r") or 0) + (d.get("disk_w") or 0)))
        nt = d.get("nvme_temp")
        self.io_rows.set("temp", units.temp(nt), theme.temp_color(nt))
        drives = d.get("disks") or []
        self.io_rows.set("drives", str(len(drives)))
        self.io_rows.set("uptime", units.duration(d.get("uptime")))

        mounts = [x.get("mount", "") for x in drives if x.get("mount")]
        if mounts != self._mounts:
            # A lista de unidades so' chega com o primeiro snapshot; ate' la' a
            # pilula mostra um palpite, e trocar de unidade so' e' possivel aqui.
            self._mounts = mounts
            self._sync_opcoes_bench()
        self._sync_drives(drives)
        self._sync_saude()

    def _sync_modulos(self, modulos: list) -> None:
        """Um pente por linha, com a faixa de cor que ele mesmo declara.

        O rotulo vem do SPD e ja' voltou sujo de uma leitura real (byte nulo no
        meio do nome), entao aqui ele e' cortado no tamanho e nunca concatenado
        cru com o resto da tela.
        """
        uteis = [m for m in modulos
                 if isinstance(m, dict) and m.get("temp") is not None][:_MAX_DIMMS]
        for i in range(_MAX_DIMMS):
            linha = self.mod_rows.row(f"m{i}")
            if linha is None:
                continue
            linha.setVisible(i < len(uteis))
            if i >= len(uteis):
                continue
            mod = uteis[i]
            linha.set_label(str(mod.get("slot") or f"Pente {i + 1}")[:24])
            linha.set(units.temp(mod["temp"]),
                      theme.dimm_temp_color(mod["temp"], mod.get("high"),
                                            mod.get("critical")))
            limites = [x for x in (mod.get("high"), mod.get("critical")) if x]
            linha.set_stat(f"limite {limites[0]:.0f} / crítico {limites[-1]:.0f} °C"
                           if len(limites) == 2 else "")

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

    def _coletar_saude(self) -> tuple[list[dict], str]:
        """Junta LHM e Storage Spaces. Nunca deixa uma excecao chegar na UI."""
        do_lhm: list[dict] = []
        try:
            leitor = getattr(self.app, "lhm", None)
            if leitor is not None and hasattr(leitor, "tree"):
                do_lhm = diskhealth.from_lhm_tree(leitor.tree())
        except Exception:                            # noqa: BLE001
            do_lhm = []
        fisicos: list[dict] = []
        erro = ""
        if self._probe_liberado:
            try:
                fisicos = self._probe.read()
                erro = self._probe.erro
            except Exception:                        # noqa: BLE001
                erro = "Não foi possível consultar a saúde dos discos."
        return diskhealth.combinar(fisicos, do_lhm), erro

    def _sync_saude(self) -> None:
        discos, erro = self._coletar_saude()
        uteis = [x for x in discos if diskhealth.tem_dado(x)]
        self.saude_aviso.setVisible(not uteis)
        if not uteis:
            self.saude_aviso.setText(
                erro or "Nenhum disco desta máquina reporta dados de saúde (SMART).")
            self.saude_aviso.setStyleSheet(
                f"color: {theme.WARN if erro else theme.FAINT}; background: transparent;")

        while len(self._saude_widgets) < len(uteis):
            self._saude_widgets.append(self._nova_coluna_saude(len(self._saude_widgets)))
        for i, col in enumerate(self._saude_widgets):
            col["root"].setVisible(i < len(uteis))
            if i < len(uteis):
                _pintar_saude(col, uteis[i])

    def _nova_coluna_saude(self, indice: int) -> dict:
        raiz = QWidget()
        box = QVBoxLayout(raiz)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(theme.scaled(4))
        titulo = label("", 9.5, QFont.Weight.DemiBold, theme.TXT)
        titulo.setWordWrap(True)
        sub = label("", 7.5, QFont.Weight.Normal, theme.FAINT)
        linha = QHBoxLayout()
        linha.setSpacing(theme.scaled(6))
        badge = Badge("", theme.FAINT)
        linha.addWidget(badge)
        linha.addStretch(1)
        rows = MetricList(_SAUDE_ROWS)
        box.addWidget(titulo)
        box.addWidget(sub)
        box.addLayout(linha)
        box.addWidget(rows)
        self.saude_grid.addWidget(raiz, indice // 3, indice % 3)
        self.saude_grid.setColumnStretch(indice % 3, 1)
        return {"root": raiz, "titulo": titulo, "sub": sub, "badge": badge, "rows": rows}


class _Escolha(PillButton):
    """Pilula que mostra a opção atual e abre um menu com as outras."""

    def __init__(self, cor: str, opcoes, escolher) -> None:
        super().__init__("", cor)
        self._opcoes = opcoes
        self._escolher = escolher
        self.clicked.connect(self._abrir)

    def _abrir(self) -> None:
        menu = QMenu(self)
        for rotulo, valor in self._opcoes():
            menu.addAction(rotulo, lambda v=valor: self._escolher(v))
        menu.exec(self.mapToGlobal(QPoint(0, self.height() + 4)))

    def mostrar(self, texto: str) -> None:
        self.setText(f"{texto}  ▾")


class _FaseToggle(PillButton):
    """Pílula que liga e desliga uma fase do teste."""

    def __init__(self, chave: str, rotulo: str) -> None:
        super().__init__(f"✓ {rotulo}", theme.GPU)
        self.chave = chave
        self._rotulo = rotulo
        self._ativo = True

    def set_ativo(self, ativo: bool) -> None:
        # A comparacao evita remontar a folha de estilo a cada snapshot: a tela
        # sincroniza as opcoes junto com os dados, duas vezes por segundo.
        if ativo == self._ativo:
            return
        self._ativo = ativo
        self.setText(f"✓ {self._rotulo}" if ativo else self._rotulo)
        self.set_color(theme.GPU if ativo else theme.MUTE)


def _rotulo_tamanho(mib: int) -> str:
    return f"{mib} MiB" if mib < 1024 else f"{mib // 1024} GiB"


def _rotulo_tempo(segundos: float) -> str:
    return f"{segundos:.1f} s".replace(".", ",")


def _opcoes_tamanho() -> list[tuple[str, int]]:
    return [(_rotulo_tamanho(m), m) for m in diskbench.TAMANHOS_MIB]


def _opcoes_tempo() -> list[tuple[str, float]]:
    return [(_rotulo_tempo(s), s) for s in diskbench.SEGUNDOS_POR_FASE]


def _escrito(gb: float | None) -> str:
    """Total escrito: TB quando ja' passou disso, senao GB."""
    if gb is None:
        return units.DASH
    return f"{gb / 1024:.2f} TB" if gb >= 1024 else f"{gb:.0f} GB"


def _horas(h: float | None) -> str:
    if h is None:
        return units.DASH
    return f"{h:.0f} h  ({h / 24:.0f} dias)"


def _cor_saude(estado: str) -> str:
    return {"healthy": theme.OK, "warning": theme.WARN}.get(estado.lower(), theme.BAD)


def _contador(disco: dict, chave: str) -> tuple[str, str] | None:
    """Contador de erro so' aparece se a maquina de fato o reportou.

    Aqui zero e' informacao boa — quer dizer "nenhum erro ate' agora". O que nao
    pode e' inventar zero para um disco que nunca respondeu o contador, porque
    isso transforma "nao sei" em "esta' tudo bem".
    """
    if chave not in disco:
        return None
    valor = disco[chave]
    return f"{valor:.0f}", theme.OK if valor <= 0 else theme.BAD


def _pintar_saude(col: dict, disco: dict) -> None:
    col["titulo"].setText(disco.get("name") or "Disco")
    detalhe = [x for x in (disco.get("bus"), disco.get("media")) if x]
    letras = disco.get("letters") or []
    if letras:
        detalhe.append(" ".join(letras))
    if disco.get("size"):
        detalhe.append(units.size(disco["size"]))
    col["sub"].setText("  ·  ".join(detalhe))

    estado = disco.get("health")
    col["badge"].setVisible(bool(estado))
    if estado:
        col["badge"].update_badge(estado.lower(), _cor_saude(estado))

    rows: MetricList = col["rows"]
    life = disco.get("life")
    temp = disco.get("temp")
    temp_max = disco.get("temp_max")
    valores: dict[str, tuple[str, str] | None] = {
        "life": (units.percent(life), theme.score_color(life)) if life is not None else None,
        "written": (_escrito(disco.get("written_gb")), theme.TXT)
        if "written_gb" in disco else None,
        "read": (_escrito(disco.get("read_gb")), theme.TXT) if "read_gb" in disco else None,
        "hours": (_horas(disco.get("hours")), theme.TXT) if "hours" in disco else None,
        "temp": (units.temp(temp), theme.temp_color(temp)) if temp is not None else None,
        "temp_max": (units.temp(temp_max), theme.temp_color(temp_max))
        if temp_max is not None else None,
        "errors_read": _contador(disco, "errors_read"),
        "errors_write": _contador(disco, "errors_write"),
        "errors": _contador(disco, "errors"),
        "spare": (units.percent(disco.get("spare")), theme.score_color(disco.get("spare")))
        if "spare" in disco else None,
        "cycles": (f"{disco['power_cycles']:.0f}", theme.TXT)
        if "power_cycles" in disco else None,
    }
    for chave, _rotulo in _SAUDE_ROWS:
        linha = rows.row(chave)
        if linha is None:
            continue
        par = valores.get(chave)
        # Linha sem leitura some da lista: travessao repetido nao informa nada e
        # ainda faz parecer que o disco esta' escondendo alguma coisa.
        linha.setVisible(par is not None)
        if par is not None:
            linha.set(par[0], par[1])
