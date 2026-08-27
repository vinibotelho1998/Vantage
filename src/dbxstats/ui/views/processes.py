"""Tela de processos: quem esta consumindo CPU e memoria agora, e o que fazer.

Ver o vilao da CPU e ter de abrir o Gerenciador de Tarefas para agir e' meio
caminho. Aqui a mesma lista encerra, muda prioridade e prende o processo em
nucleos escolhidos; a decisao do que e' proibido mora em sensors/procs.py.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QCheckBox,
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLineEdit,
    QMenu,
    QPushButton,
    QRadioButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from ... import theme
from ...core import units
from ...sensors import procs as P
from ..components import Card, KpiStrip, PillButton, label
from ..confirm import confirmar
from .base import View

_HEADERS = ["Processo", "PID", "CPU", "Memória", "Threads"]
_ORDENS = ("name", "pid", "cpu", "ram", "threads")
"""Coluna -> criterio de ordenacao, na mesma ordem de _HEADERS."""
_ROTULO_ORDEM = {"name": "nome", "pid": "PID", "cpu": "CPU",
                 "ram": "memória", "threads": "threads"}


def _chave_ordem(criterio: str):
    if criterio == "name":
        return lambda p: p.name.lower()
    if criterio == "pid":
        return lambda p: p.pid
    if criterio == "ram":
        return lambda p: p.ram_mb
    if criterio == "threads":
        return lambda p: p.threads
    return lambda p: p.cpu
_KPIS = [
    ("procs", "Processos", ""), ("threads", "Threads", ""), ("cpu", "CPU total", "%"),
    ("ram", "RAM usada", "GB"), ("top", "Maior consumidor", ""),
]
_DICA = "Clique num processo da lista para encerrar, priorizar ou fixar em núcleos."
_RISCO_REALTIME = (
    "Em tempo real o processo passa na frente do próprio Windows: se ele travar "
    "ou consumir tudo, o mouse, o teclado e o áudio param junto e sobra reiniciar "
    "no botão. Use só em algo que você sabe que se comporta, e volte para Alta "
    "depois."
)


class PrioridadeDialog(QDialog):
    """Escolhe a faixa de prioridade do processo.

    O aviso de que a escolha morre com o processo esta' na tela porque o Windows
    nao guarda isso em lugar nenhum; sem dizer, a pessoa reabre o jogo, ve tudo
    em Normal de novo e acha que o app nao aplicou nada.
    """

    def __init__(self, nome: str, pid: int, atual, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("SettingsRoot")
        self.setWindowTitle("DBX Stats: prioridade")
        self.setModal(True)
        self.setMinimumWidth(theme.scaled(420))

        root = QVBoxLayout(self)
        root.setContentsMargins(*(theme.scaled(18),) * 4)
        root.setSpacing(theme.scaled(8))
        root.addWidget(label(f"Prioridade de {nome}", 12, QFont.Weight.Bold))
        agora = P.rotulo_prioridade(atual) or "não foi possível ler"
        root.addWidget(label(f"PID {pid} · agora: {agora}", 8.5, color=theme.MUTE))

        grupo = QButtonGroup(self)
        self._botoes: dict[str, QRadioButton] = {}
        for prio in P.PRIORIDADES:
            radio = QRadioButton(prio.rotulo + (f": {prio.dica}" if prio.dica else ""))
            radio.setChecked(atual is not None and atual == prio.valor)
            grupo.addButton(radio)
            self._botoes[prio.chave] = radio
            root.addWidget(radio)
        if grupo.checkedButton() is None:
            self._botoes["normal"].setChecked(True)

        self._alerta = label("", 8.5, color=theme.BAD)
        self._alerta.setWordWrap(True)
        self._alerta.setVisible(False)
        root.addWidget(self._alerta)
        self._botoes["realtime"].toggled.connect(self._pintar_alerta)

        aviso = label("Vale só até o processo fechar; o Windows não guarda essa escolha.",
                      8, color=theme.FAINT)
        aviso.setWordWrap(True)
        root.addWidget(aviso)

        linha = QHBoxLayout()
        linha.addStretch(1)
        cancelar = QPushButton("Cancelar")
        cancelar.clicked.connect(self.reject)
        cancelar.setDefault(True)
        aplicar = QPushButton("Aplicar")
        aplicar.setObjectName("Accent")
        aplicar.clicked.connect(self.accept)
        linha.addWidget(cancelar)
        linha.addWidget(aplicar)
        root.addLayout(linha)

    def _pintar_alerta(self, marcado: bool) -> None:
        self._alerta.setText(_RISCO_REALTIME if marcado else "")
        self._alerta.setVisible(bool(marcado))

    def escolha(self) -> str:
        return next((chave for chave, b in self._botoes.items() if b.isChecked()), "normal")


class AfinidadeDialog(QDialog):
    """Marca em quais nucleos logicos o processo pode rodar."""

    def __init__(self, nome: str, pid: int, atuais, total: int, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("SettingsRoot")
        self.setWindowTitle("DBX Stats: afinidade")
        self.setModal(True)
        self.setMinimumWidth(theme.scaled(460))
        self._total = max(1, int(total))

        root = QVBoxLayout(self)
        root.setContentsMargins(*(theme.scaled(18),) * 4)
        root.setSpacing(theme.scaled(9))
        root.addWidget(label(f"Núcleos de {nome}", 12, QFont.Weight.Bold))
        # Sem essa frase o par 0/1 parece "dois nucleos" e a pessoa deixa o jogo
        # preso nas duas metades do mesmo nucleo fisico, achando que dobrou.
        root.addWidget(label(
            f"PID {pid} · em CPUs com SMT os vizinhos (0 e 1, 2 e 3…) são o mesmo "
            "núcleo físico.", 8.5, color=theme.MUTE))

        grade = QGridLayout()
        grade.setSpacing(theme.scaled(4))
        marcados = set(atuais) if atuais else set(range(self._total))
        self._caixas: list[QCheckBox] = []
        for i in range(self._total):
            caixa = QCheckBox(str(i))
            caixa.setChecked(i in marcados)
            caixa.toggled.connect(self._pintar_resumo)
            self._caixas.append(caixa)
            grade.addWidget(caixa, i // 8, i % 8)
        root.addLayout(grade)

        atalhos = QHBoxLayout()
        atalhos.setSpacing(theme.scaled(8))
        for texto, alvo in (("Todos", list(range(self._total))),
                            ("Nenhum", []),
                            ("Primeira metade", list(range(max(1, self._total // 2))))):
            pill = PillButton(texto, theme.MUTE)
            pill.clicked.connect(lambda n=alvo: self._marcar(n))
            atalhos.addWidget(pill)
        atalhos.addStretch(1)
        root.addLayout(atalhos)

        digitar = QHBoxLayout()
        digitar.setSpacing(theme.scaled(8))
        self._campo = QLineEdit()
        self._campo.setPlaceholderText("Atalho: 0-3, 8")
        self._campo.returnPressed.connect(self._aplicar_texto)
        digitar.addWidget(self._campo, 1)
        marcar = PillButton("Marcar", theme.CPU)
        marcar.clicked.connect(self._aplicar_texto)
        digitar.addWidget(marcar)
        root.addLayout(digitar)

        self._resumo = label("", 8.5, color=theme.MUTE)
        self._resumo.setWordWrap(True)
        root.addWidget(self._resumo)
        if not atuais:
            root.addWidget(label("Não deu para ler a afinidade atual; o que está "
                                 "marcado é um palpite.", 8, color=theme.WARN))

        linha = QHBoxLayout()
        linha.addStretch(1)
        cancelar = QPushButton("Cancelar")
        cancelar.clicked.connect(self.reject)
        cancelar.setDefault(True)
        aplicar = QPushButton("Aplicar")
        aplicar.setObjectName("Accent")
        aplicar.clicked.connect(self._aceitar)
        linha.addWidget(cancelar)
        linha.addWidget(aplicar)
        root.addLayout(linha)
        self._pintar_resumo()

    def nucleos(self) -> list[int]:
        return [i for i, caixa in enumerate(self._caixas) if caixa.isChecked()]

    def _marcar(self, nucleos) -> None:
        alvo = set(nucleos)
        for i, caixa in enumerate(self._caixas):
            caixa.setChecked(i in alvo)

    def _aplicar_texto(self) -> None:
        try:
            self._marcar(P.parse_nucleos(self._campo.text(), self._total))
        except ValueError as erro:
            self._dizer(str(erro), theme.BAD)
            return
        self._campo.clear()

    def _pintar_resumo(self, *_a) -> None:
        escolhidos = self.nucleos()
        if not escolhidos:
            self._dizer("Nenhum núcleo marcado; sem pelo menos um, o processo não roda.",
                        theme.WARN)
        elif len(escolhidos) == self._total:
            self._dizer(f"Todos os {self._total} núcleos (sem restrição).", theme.MUTE)
        else:
            self._dizer(f"{len(escolhidos)} de {self._total} · "
                        f"{P.formatar_nucleos(escolhidos)}", theme.MUTE)

    def _dizer(self, texto: str, cor: str) -> None:
        self._resumo.setText(texto)
        self._resumo.setStyleSheet(f"color: {cor}; background: transparent;")

    def _aceitar(self) -> None:
        if not self.nucleos():
            self._pintar_resumo()
            return
        self.accept()


class ProcessesView(View):
    key = "processes"
    title = "Processos"
    glyph = "☰"

    def __init__(self, app) -> None:
        super().__init__(app)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(theme.scaled(theme.GAP))

        self.kpi = KpiStrip(_KPIS, columns=5)
        root.addWidget(self.kpi)

        bar = QHBoxLayout()
        bar.setSpacing(theme.scaled(8))
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("Filtrar por nome…")
        self.filter.setMaximumWidth(theme.scaled(300))
        bar.addWidget(self.filter)
        self.sort_btn = PillButton("Ordenar por CPU", theme.accent_color(self.cfg.accent))
        self.sort_btn.clicked.connect(self._toggle_sort)
        bar.addWidget(self.sort_btn)
        bar.addStretch(1)
        self.prio_btn = PillButton("Prioridade", theme.FAINT)
        self.prio_btn.clicked.connect(self._prioridade)
        bar.addWidget(self.prio_btn)
        self.afin_btn = PillButton("Afinidade", theme.FAINT)
        self.afin_btn.clicked.connect(self._afinidade)
        bar.addWidget(self.afin_btn)
        self.kill_btn = PillButton("Finalizar", theme.FAINT)
        self.kill_btn.clicked.connect(self._finalizar)
        bar.addWidget(self.kill_btn)
        root.addLayout(bar)

        self._aqueceu = False
        self.status = label(_DICA, 8.5, color=theme.FAINT)
        self.status.setWordWrap(True)
        root.addWidget(self.status)

        # Faixa do processo escolhido. A tabela se reordena a cada 2,5 s e o
        # destaque da linha viaja junto: dizer em letra grande QUEM esta' na
        # mira e' o que evita apertar "Finalizar" achando que era outro.
        self.escolhido = Card("Nenhum processo selecionado", theme.FAINT,
                              "clique numa linha da lista")
        self.escolhido_txt = label("Escolha um processo para agir sobre ele.", 9,
                                   color=theme.MUTE)
        self.escolhido_txt.setWordWrap(True)
        self.escolhido.add(self.escolhido_txt)
        root.addWidget(self.escolhido)

        card = Card("Em execução", theme.RAM, "atualiza a cada 2,5 s")
        self.table = QTableWidget(0, len(_HEADERS))
        self.table.setHorizontalHeaderLabels(_HEADERS)
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._menu)
        self.table.itemSelectionChanged.connect(self._selecao_mudou)
        # O realce padrao do tema e' discreto demais para uma lista que se
        # reordena sozinha: com a linha mudando de lugar, o azul fraco se perde.
        accent = theme.accent_color(self.cfg.accent)
        self.table.setStyleSheet(
            f"QTableWidget::item:selected {{ background: {accent}; color: #06121c; }}"
            f"QTableWidget {{ selection-background-color: {accent}; }}")
        header = self.table.horizontalHeader()
        header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        header.setSectionsClickable(True)
        header.sectionClicked.connect(self._ordenar_por)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for i, width in ((1, 80), (2, 100), (3, 120), (4, 90)):
            header.setSectionResizeMode(i, QHeaderView.ResizeMode.Fixed)
            self.table.setColumnWidth(i, theme.scaled(width))
            self.table.horizontalHeaderItem(i).setTextAlignment(
                int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter))
        card.add(self.table, 1)
        root.addWidget(card, 1)

        self._sel_pid: int | None = None
        self._ordem = "cpu"
        self._desc = True
        self._marcar_ordem()

    def _ordenar_por(self, coluna: int) -> None:
        """Clique no cabecalho ordena por aquela coluna; de novo, inverte.

        Vale mais que um botao de alternar entre duas ordens: quem procura "o
        que esta' comendo a RAM" pensa na coluna, nao num modo escondido atras
        de um botao.
        """
        chave = _ORDENS[coluna]
        if chave == self._ordem:
            self._desc = not self._desc
        else:
            self._ordem = chave
            # Numero comeca do maior, nome comeca do A: e' o que se espera.
            self._desc = chave != "name"
        self._marcar_ordem()

    def _marcar_ordem(self) -> None:
        seta = " ▼" if self._desc else " ▲"
        for i, titulo in enumerate(_HEADERS):
            item = self.table.horizontalHeaderItem(i)
            if item is not None:
                item.setText(titulo + (seta if _ORDENS[i] == self._ordem else ""))
        self.sort_btn.setText(f"Ordem: {_ROTULO_ORDEM[self._ordem]}"
                              + (" ↓" if self._desc else " ↑"))

    def _toggle_sort(self) -> None:
        """O botao percorre as ordens, para quem prefere nao clicar no cabecalho."""
        chaves = [c for c in _ORDENS if c]
        atual = chaves.index(self._ordem) if self._ordem in chaves else 0
        self._ordem = chaves[(atual + 1) % len(chaves)]
        self._desc = self._ordem != "name"
        self._marcar_ordem()

    def on_settings_changed(self) -> None:
        self.sort_btn.set_color(theme.accent_color(self.cfg.accent))

    def _alvo(self) -> tuple[int, str] | None:
        """(pid, nome) da linha selecionada, lidos da propria celula.

        Vem do dado guardado na celula, e nao do indice da linha: a lista se
        reordena sozinha e um indice guardado apontaria para outro processo na
        proxima coleta.
        """
        linha = self.table.currentRow()
        item = self.table.item(linha, 0) if linha >= 0 else None
        if item is None or not item.isSelected():
            return None
        return item.data(Qt.ItemDataRole.UserRole)

    def _selecao_mudou(self) -> None:
        alvo = self._alvo()
        self._sel_pid = alvo[0] if alvo else None
        ativo = alvo is not None
        self.prio_btn.set_color(theme.RAM if ativo else theme.FAINT)
        self.afin_btn.set_color(theme.CPU if ativo else theme.FAINT)
        self.kill_btn.set_color(theme.BAD if ativo else theme.FAINT)
        if ativo:
            self._dizer(f"{alvo[1]} (PID {alvo[0]}) selecionado.", theme.MUTE)
        self._pintar_escolhido(alvo)

    def _pintar_escolhido(self, alvo) -> None:
        """Faixa do topo com quem esta' na mira, e o que ja' se sabe dele."""
        if alvo is None:
            self.escolhido.set_title("Nenhum processo selecionado")
            self.escolhido.set_hint("clique numa linha da lista", theme.FAINT)
            self.escolhido_txt.setText("Escolha um processo para agir sobre ele.")
            self.escolhido_txt.setStyleSheet(f"color: {theme.MUTE}; background: transparent;")
            return
        pid, nome = alvo
        self.escolhido.set_title(f"{nome}   ·   PID {pid}")
        bloqueio = P.bloqueio_encerrar(nome, pid)
        if bloqueio:
            self.escolhido.set_hint("protegido pelo Windows", theme.BAD)
            self.escolhido_txt.setText(bloqueio)
            self.escolhido_txt.setStyleSheet(f"color: {theme.BAD}; background: transparent;")
            return
        self.escolhido.set_hint("pronto para agir", theme.OK)
        self.escolhido_txt.setStyleSheet(f"color: {theme.TXT}; background: transparent;")
        d = P.detalhes(pid, nome)
        partes = []
        rotulo = P.rotulo_prioridade(d.get("prioridade"))
        if rotulo:
            partes.append(f"Prioridade: {rotulo}")
        nucleos = d.get("nucleos")
        if nucleos:
            partes.append(f"Núcleos: {P.formatar_nucleos(nucleos)}")
        aviso = P.aviso_encerrar(nome)
        if aviso:
            partes.append(aviso)
        self.escolhido_txt.setText("   ·   ".join(partes)
                                   or "Pronto para priorizar, fixar em núcleos ou finalizar.")

    def _restaurar_selecao(self, rows) -> None:
        """Mantem o destaque no mesmo processo mesmo quando a ordem muda.

        A lista se reordena por CPU a cada 2,5 s. Preso na linha, o destaque
        pularia sozinho para outro processo entre o olhar e o clique, e o botao
        de finalizar acertaria quem nao devia.
        """
        if self._sel_pid is None:
            return
        linha = next((i for i, p in enumerate(rows) if p.pid == self._sel_pid), -1)
        if linha == self.table.currentRow() and linha >= 0:
            return
        self.table.blockSignals(True)
        if linha < 0:
            self.table.clearSelection()
            self.table.setCurrentCell(-1, -1)
        else:
            self.table.selectRow(linha)
        self.table.blockSignals(False)
        if linha < 0:
            self._sel_pid = None
            self._selecao_mudou()

    def _menu(self, pos) -> None:
        item = self.table.itemAt(pos)
        if item is None:
            return
        self.table.selectRow(item.row())
        alvo = self._alvo()
        if alvo is None:
            return
        menu = QMenu(self)
        menu.addAction("Mudar prioridade…", self._prioridade)
        menu.addAction("Mudar afinidade de CPU…", self._afinidade)
        menu.addSeparator()
        if P.bloqueio_encerrar(alvo[1], alvo[0]):
            protegido = menu.addAction("Finalizar (protegido pelo Windows)")
            protegido.setEnabled(False)
        else:
            menu.addAction("Finalizar processo", self._finalizar)
        menu.exec(self.table.viewport().mapToGlobal(pos))

    def _dizer(self, texto: str, cor: str = theme.MUTE) -> None:
        self.status.setText(texto)
        self.status.setStyleSheet(f"color: {cor}; background: transparent;")

    def _finalizar(self) -> None:
        alvo = self._alvo()
        if alvo is None:
            self._dizer("Escolha um processo na lista primeiro.", theme.WARN)
            return
        pid, nome = alvo
        bloqueio = P.bloqueio_encerrar(nome, pid)
        if bloqueio:
            self._dizer(bloqueio, theme.BAD)
            return
        extra = P.aviso_encerrar(nome)
        texto = (f"{nome} (PID {pid}) será encerrado na hora, sem chance de salvar "
                 "o que estiver aberto nele.")
        if extra:
            texto += "\n\n" + extra
        if not confirmar("Finalizar este processo?", texto, "Finalizar", True, self):
            self._dizer("Nada foi encerrado.", theme.MUTE)
            return
        ok, msg = P.encerrar(pid, nome)
        self._dizer(msg, theme.OK if ok else theme.BAD)

    def _prioridade(self) -> None:
        alvo = self._alvo()
        if alvo is None:
            self._dizer("Escolha um processo na lista primeiro.", theme.WARN)
            return
        pid, nome = alvo
        dlg = PrioridadeDialog(nome, pid, P.detalhes(pid, nome)["prioridade"], self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        chave = dlg.escolha()
        prio = P.prioridade_por_chave(chave)
        # Segunda pergunta so' para tempo real: e' a unica opcao que pode deixar a
        # maquina sem responder ao mouse, e o radio marcado por engano nao pode
        # ser suficiente para chegar la'.
        if prio is not None and prio.perigosa and not confirmar(
                f"Colocar {nome} em tempo real?", _RISCO_REALTIME,
                "Entendo o risco, aplicar", True, self):
            self._dizer("Prioridade continua como estava.", theme.MUTE)
            return
        ok, msg = P.mudar_prioridade(pid, nome, chave)
        self._dizer(msg, theme.OK if ok else theme.BAD)

    def _afinidade(self) -> None:
        alvo = self._alvo()
        if alvo is None:
            self._dizer("Escolha um processo na lista primeiro.", theme.WARN)
            return
        pid, nome = alvo
        total = P.nucleos_totais()
        dlg = AfinidadeDialog(nome, pid, P.detalhes(pid, nome)["nucleos"], total, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        ok, msg = P.mudar_afinidade(pid, nome, dlg.nucleos())
        self._dizer(msg, theme.OK if ok else theme.BAD)

    def on_system(self, d: dict) -> None:
        rows = self.app.procs.snapshot()
        # A primeira passada do monitor so' arma o contador de CPU do psutil; o
        # numero util aparece na segunda, uns tres segundos depois de abrir. Sem
        # dizer nada, a aba parecia quebrada nesse intervalo.
        if not rows and not self._aqueceu:
            self._dizer("Medindo o uso de CPU dos processos...", theme.FAINT)
        elif rows and not self._aqueceu:
            self._aqueceu = True
            self._dizer(_DICA, theme.FAINT)
        needle = self.filter.text().strip().lower()
        if needle:
            rows = [p for p in rows if needle in p.name.lower()]
        rows = sorted(rows, key=_chave_ordem(self._ordem), reverse=self._desc)

        count, threads = self.app.procs.totals()
        self.kpi.set("procs", str(count or (d or {}).get("processes", 0)), theme.TXT)
        self.kpi.set("threads", str(threads), theme.TXT)
        self.kpi.set("cpu", f"{(d or {}).get('cpu_pct', 0):.0f}",
                     theme.load_color((d or {}).get("cpu_pct")))
        self.kpi.set("ram", f"{(d or {}).get('ram_used', 0):.1f}", theme.RAM,
                     f"de {(d or {}).get('ram_total', 0):.0f} GB")
        if rows:
            top = rows[0]
            self.kpi.set("top", top.name[:12], theme.WARN,
                         f"{top.cpu:.1f}% · {top.ram_mb:.0f} MB")

        # Sinais mudos durante a remontagem: encolher a tabela faz o Qt mexer na
        # selecao sozinho, e o app leria isso como "o usuario escolheu outro
        # processo" bem no meio de uma linha que ainda nem tem dado novo.
        alvo = self._sel_pid
        self.table.setUpdatesEnabled(False)
        self.table.blockSignals(True)
        if self.table.rowCount() != len(rows):
            self.table.setRowCount(len(rows))
            for r in range(len(rows)):
                for c in range(len(_HEADERS)):
                    if self.table.item(r, c) is None:
                        item = QTableWidgetItem("")
                        if c:
                            item.setTextAlignment(int(Qt.AlignmentFlag.AlignRight
                                                      | Qt.AlignmentFlag.AlignVCenter))
                        self.table.setItem(r, c, item)
                self.table.setRowHeight(r, theme.scaled(22))
        for r, p in enumerate(rows):
            name = self.table.item(r, 0)
            name.setText(("🎮  " if p.is_game else "") + p.name)
            name.setForeground(QBrush(QColor(theme.FPS if p.is_game else theme.TXT)))
            name.setFont(QFont(theme.FONT_UI, max(7, theme.scaled(8.5)),
                               QFont.Weight.DemiBold if p.is_game else QFont.Weight.Normal))
            # Identidade junto da celula: e' o que as acoes leem na hora do clique.
            name.setData(Qt.ItemDataRole.UserRole, (p.pid, p.name))
            self.table.item(r, 1).setText(str(p.pid))
            cpu = self.table.item(r, 2)
            cpu.setText(f"{p.cpu:.1f}%")
            cpu.setForeground(QBrush(QColor(theme.load_color(p.cpu * 4))))
            self.table.item(r, 3).setText(units.size(p.ram_mb * 1024 ** 2))
            self.table.item(r, 4).setText(str(p.threads))
        self.table.blockSignals(False)
        self._sel_pid = alvo
        self._restaurar_selecao(rows)
        self.table.setUpdatesEnabled(True)
