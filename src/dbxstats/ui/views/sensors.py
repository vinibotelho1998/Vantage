"""Tela de sensores: arvore completa do LibreHardwareMonitor com mín/méd/máx."""
from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLineEdit,
    QMenu,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from ... import theme
from ...core import units
from ..components import Badge, Card, PillButton, label
from .base import View

_HEADERS = ["★", "Sensor", "Atual", "Mínimo", "Médio", "Máximo"]
_COL_STAR = 0
_COL_NAME = 1
_COL_NOW = 2
"""Primeira coluna numerica. As de estatistica vem depois dela, ate' o fim."""

_ESTRELA_CHEIA = "★"
_ESTRELA_VAZIA = "☆"
_TITULO_FAVORITOS = "★ Favoritos"

_KIND_COLORS = {
    "Temperature": theme.WARN, "Power": theme.DISK, "Load": theme.CPU,
    "Clock": theme.FPS, "Fan": theme.GPU, "Voltage": theme.RAM,
    "Control": theme.GPU, "Data": theme.MUTE, "SmallData": theme.MUTE,
    "Throughput": theme.NET, "Level": theme.RAM,
}


class SensorsView(View):
    key = "sensors"
    title = "Sensores"
    glyph = "◈"

    def __init__(self, app) -> None:
        super().__init__(app)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(theme.scaled(theme.GAP))

        bar = QHBoxLayout()
        bar.setSpacing(theme.scaled(8))
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("Filtrar sensores (ex.: temp, fan, core)…")
        self.filter.setMaximumWidth(theme.scaled(320))
        self.filter.textChanged.connect(self._rebuild_soon)
        bar.addWidget(self.filter)
        self.reset_btn = PillButton("Zerar mín/máx", theme.MUTE)
        self.reset_btn.clicked.connect(self.app.clear_stats)
        bar.addWidget(self.reset_btn)
        self.export_btn = PillButton("Exportar CSV", theme.accent_color(self.cfg.accent))
        self.export_btn.clicked.connect(self._export)
        bar.addWidget(self.export_btn)
        bar.addStretch(1)
        self.count_badge = Badge("0 sensores", theme.FAINT)
        bar.addWidget(self.count_badge)
        root.addLayout(bar)

        # A dica do card e' o unico lugar que ensina o recurso: numa lista de
        # centenas de linhas, ninguem descobre a estrela por conta propria.
        card = Card("Todos os sensores", theme.accent_color(self.cfg.accent),
                    "LibreHardwareMonitor · clique na ★ para fixar no topo")
        self.table = QTableWidget(0, len(_HEADERS))
        self.table.setHorizontalHeaderLabels(_HEADERS)
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        # A tabela e' so' leitura, mas a estrela precisa responder ao clique.
        # `cellClicked` sai do release do botao esquerdo sobre uma celula valida
        # e nao depende do modo de selecao — por isso a lista continua sem
        # destaque de linha, e o botao direito cai so' no menu de contexto.
        self.table.cellClicked.connect(self._clique)
        # O menu de contexto poe a acao em palavras para quem nao decodifica o
        # glifo; e' o mesmo padrao da tabela de processos.
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._menu)
        header = self.table.horizontalHeader()
        header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        header.setSectionResizeMode(_COL_STAR, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(_COL_STAR, theme.scaled(28))
        self.table.horizontalHeaderItem(_COL_STAR).setTextAlignment(
            int(Qt.AlignmentFlag.AlignCenter))
        header.setSectionResizeMode(_COL_NAME, QHeaderView.ResizeMode.Stretch)
        for i in range(_COL_NOW, len(_HEADERS)):
            header.setSectionResizeMode(i, QHeaderView.ResizeMode.Fixed)
            self.table.setColumnWidth(i, theme.scaled(110))
            self.table.horizontalHeaderItem(i).setTextAlignment(
                int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter))
        card.add(self.table, 1)
        root.addWidget(card, 1)

        # Falha de sensor nao pode virar "aguardando" eterno: numa maquina nova
        # e' justamente aqui que o app parece quebrado sem explicar nada.
        self.empty = label("Procurando sensores…", 9, QFont.Weight.Normal, theme.FAINT)
        self.empty.setWordWrap(True)
        root.addWidget(self.empty)

        self.acoes = QHBoxLayout()
        self.acoes.setSpacing(theme.scaled(8))
        self.btn_retry = PillButton("Tentar de novo", theme.OK)
        self.btn_retry.clicked.connect(self._retry)
        self.btn_logs = PillButton("Abrir pasta de logs", theme.MUTE)
        self.btn_logs.clicked.connect(self._open_logs)
        self.acoes.addWidget(self.btn_retry)
        self.acoes.addWidget(self.btn_logs)
        self.acoes.addStretch(1)
        root.addLayout(self.acoes)
        self._mostrar_acoes(False)

        self._keys: list[str] = []
        self._rows: dict[str, list[int]] = {}
        """Chave -> linhas que a mostram.

        E' lista, e nao um numero, porque o favorito aparece duas vezes: na
        secao do topo e no grupo de hardware dele. As duas tem que receber o
        valor a cada ciclo, senao uma delas congela num numero velho.
        """
        self._nodes: list = []
        """Ultimo ciclo ja' filtrado, para redesenhar no ato do clique."""
        self._dirty = True

    def _rebuild_soon(self) -> None:
        self._dirty = True

    def on_activate(self) -> None:
        self._dirty = True

    def on_settings_changed(self) -> None:
        self.export_btn.set_color(theme.accent_color(self.cfg.accent))
        # O acento pinta os cabecalhos de hardware; sem remontar, a lista fica
        # com a cor antiga ate' a proxima mudanca de filtro.
        self._dirty = True

    def _mostrar_acoes(self, visivel: bool) -> None:
        self.btn_retry.setVisible(visivel)
        self.btn_logs.setVisible(visivel)

    def _retry(self) -> None:
        self.app.lhm.start()
        self.empty.setText("Tentando abrir os sensores de novo…")
        self.empty.setStyleSheet(f"color: {theme.MUTE}; background: transparent;")

    def _open_logs(self) -> None:
        from ... import paths
        os.startfile(str(paths.logs_dir()))  # noqa: S606

    def _favoritos(self) -> list[str]:
        """Chaves marcadas, sempre como lista de texto.

        Le com getattr porque um app de teste (ou um settings de versao antiga
        recem-carregado) pode nao ter o campo — e favorito nenhum e' um estado
        valido, nao um motivo para a aba inteira nao abrir.
        """
        return [str(k) for k in (getattr(self.cfg, "sensor_favorites", None) or [])]

    def _guardar(self) -> None:
        """Persiste a escolha. `save_settings` pode nao existir num app de teste."""
        salvar = getattr(self.app, "save_settings", None)
        if callable(salvar):
            salvar()

    def _alternar_favorito(self, key: str) -> None:
        if not key:
            return
        favoritos = self._favoritos()
        if key in favoritos:
            favoritos.remove(key)
        else:
            favoritos.append(key)
        self.cfg.sensor_favorites = favoritos
        self._guardar()
        self._dirty = True
        # Redesenha na hora, com os nodes do ultimo ciclo. Esperar o proximo
        # tick do coletor (ate' 2 s no intervalo mais lento) faria o clique
        # parecer que nao pegou, e a pessoa clicaria de novo — desmarcando.
        if self._nodes:
            self._build_table(self._nodes)
            self._update_values(self._nodes)
            self._contar(self._nodes)
            self._dirty = False

    def _chave_da_linha(self, row: int) -> str:
        """Identidade guardada na celula, nunca deduzida do indice.

        A lista muda de tamanho sozinha: sensor que some, filtro digitado,
        secao de favoritos que nasce ou morre. A linha 12 de agora nao e' a
        linha 12 do ciclo passado, entao o indice marcaria o sensor errado.
        """
        item = self.table.item(row, _COL_STAR)
        if item is None:
            return ""
        return str(item.data(Qt.ItemDataRole.UserRole) or "")

    def _clique(self, row: int, col: int) -> None:
        if col != _COL_STAR:
            return
        self._alternar_favorito(self._chave_da_linha(row))

    def _menu(self, pos) -> None:
        item = self.table.itemAt(pos)
        if item is None:
            return
        # Linha de cabecalho (hardware ou "Favoritos") nao tem chave: favoritar
        # "Processador" nao significa nada e so' sujaria o settings.
        key = self._chave_da_linha(item.row())
        if not key:
            return
        menu = QMenu(self)
        marcado = key in self._favoritos()
        texto = "Tirar dos favoritos" if marcado else "Adicionar aos favoritos"
        menu.addAction(texto, lambda: self._alternar_favorito(key))
        menu.exec(self.table.viewport().mapToGlobal(pos))

    def on_system(self, _d: dict) -> None:
        nodes = self.app.lhm.tree()
        if not nodes:
            erro = getattr(self.app.lhm, "error", "")
            if erro:
                self.empty.setText("Não consegui ler os sensores.\n" + erro)
                self.empty.setStyleSheet(f"color: {theme.WARN}; background: transparent;")
                self._mostrar_acoes(True)
            else:
                self.empty.setText("Procurando sensores…")
                self.empty.setStyleSheet(f"color: {theme.FAINT}; background: transparent;")
            self.empty.setVisible(True)
            self.count_badge.update_badge("sem sensores", theme.WARN if erro else theme.FAINT)
            return
        self.empty.setVisible(False)
        self._mostrar_acoes(False)
        needle = self.filter.text().strip().lower()
        if needle:
            nodes = [n for n in nodes
                     if needle in n.name.lower() or needle in n.hardware.lower()
                     or needle in n.kind.lower()]
        keys = [n.key for n in nodes]
        self._nodes = nodes
        if self._dirty or keys != self._keys:
            self._build_table(nodes)
            self._keys = keys
            self._dirty = False
        self._update_values(nodes)
        self._contar(nodes)

    def _contar(self, nodes) -> None:
        """Contador da barra. Redesenhado junto com a tabela, e nao so' no tick.

        Marcar um favorito muda a lista na hora; deixar o badge para o proximo
        ciclo poria a barra contradizendo o que ja' esta' desenhado na tela.
        """
        vistos = len(self._presentes_favoritos(nodes))
        texto = f"{len(nodes)} sensores"
        if vistos:
            texto += f" · {vistos} favoritos"
        self.count_badge.update_badge(texto, theme.MUTE)

    def _presentes_favoritos(self, nodes) -> list:
        """Favoritos que existem neste ciclo, na ordem em que foram marcados.

        A chave de um sensor que sumiu (placa desconectada, sensor renomeado
        entre versoes do LHM) fica guardada no settings de proposito — volta
        sozinha quando a peca voltar —, mas aqui ela e' ignorada: linha com
        travessao eterno so' faz a tela parecer quebrada.
        """
        presentes = {n.key: n for n in nodes}
        return [presentes[k] for k in self._favoritos() if k in presentes]

    def _build_table(self, nodes) -> None:
        self.table.setUpdatesEnabled(False)
        self.table.setRowCount(0)
        self._rows = {}
        marcados = set(self._favoritos())
        row = 0

        # Secao do topo. Sem nenhum favorito presente ela nem nasce: cabecalho
        # sozinho e' pior que ausencia nenhuma.
        vivos = self._presentes_favoritos(nodes)
        if vivos:
            row = self._secao(row, _TITULO_FAVORITOS, theme.WARN)
            for node in vivos:
                # Aqui o hardware entra no rotulo: fora do grupo dele,
                # "Temperature" sozinho nao diz de qual peca e'.
                row = self._linha(row, node, f"{node.hardware} · {node.name}", True)

        # O favorito continua no grupo original de proposito: arrancar a linha
        # deixaria um buraco silencioso no hardware, e a pessoa procuraria por
        # um sensor que "sumiu". A secao e' atalho, nao mudanca de endereco.
        current_hw = None
        for node in nodes:
            if node.hardware != current_hw:
                current_hw = node.hardware
                row = self._secao(row, current_hw,
                                  theme.accent_color(self.cfg.accent))
            row = self._linha(row, node, node.name, node.key in marcados)
        self.table.setUpdatesEnabled(True)

    def _secao(self, row: int, titulo: str, cor: str) -> int:
        self.table.insertRow(row)
        item = QTableWidgetItem(titulo)
        item.setFont(QFont(theme.FONT_UI, max(7, theme.scaled(9)), QFont.Weight.Bold))
        item.setForeground(QBrush(QColor(cor)))
        self.table.setItem(row, _COL_NAME, item)
        for c in range(len(_HEADERS)):
            if c != _COL_NAME:
                self.table.setItem(row, c, QTableWidgetItem(""))
        self.table.setRowHeight(row, theme.scaled(26))
        return row + 1

    def _linha(self, row: int, node, texto: str, favorito: bool) -> int:
        self.table.insertRow(row)
        estrela = QTableWidgetItem(_ESTRELA_CHEIA if favorito else _ESTRELA_VAZIA)
        estrela.setTextAlignment(int(Qt.AlignmentFlag.AlignCenter))
        estrela.setForeground(QBrush(QColor(theme.WARN if favorito else theme.FAINT)))
        estrela.setData(Qt.ItemDataRole.UserRole, node.key)
        estrela.setToolTip("Tirar dos favoritos" if favorito else "Marcar como favorito")
        self.table.setItem(row, _COL_STAR, estrela)
        name = QTableWidgetItem(f"    {texto}")
        name.setForeground(QBrush(QColor(theme.MUTE)))
        self.table.setItem(row, _COL_NAME, name)
        for c in range(_COL_NOW, len(_HEADERS)):
            cell = QTableWidgetItem("—")
            cell.setTextAlignment(int(Qt.AlignmentFlag.AlignRight
                                      | Qt.AlignmentFlag.AlignVCenter))
            cell.setForeground(QBrush(QColor(theme.FAINT if c > _COL_NOW else theme.TXT)))
            self.table.setItem(row, c, cell)
        self.table.setRowHeight(row, theme.scaled(22))
        self._rows.setdefault(node.key, []).append(row)
        return row + 1

    def _update_values(self, nodes) -> None:
        stats = self.app.stats
        for node in nodes:
            linhas = self._rows.get(node.key)
            if not linhas:
                continue
            color = _KIND_COLORS.get(node.kind, theme.TXT)
            if node.kind == "Temperature":
                color = theme.temp_color(node.value)
            elif node.kind in ("Load", "Control", "Level"):
                color = theme.load_color(node.value)
            agg = stats.get(node.key)
            for row in linhas:
                cur = self.table.item(row, _COL_NOW)
                cur.setText(units.sensor_value(node.value, node.unit))
                cur.setForeground(QBrush(QColor(color)))
                if agg is None:
                    continue
                mn, av, mx = agg
                for col, value in ((_COL_NOW + 1, mn), (_COL_NOW + 2, av),
                                   (_COL_NOW + 3, mx)):
                    self.table.item(row, col).setText(
                        units.sensor_value(value, node.unit))

    def _export(self) -> None:
        from ...core.export import export_sensors
        path = export_sensors(self.app.lhm.tree(), self.app.stats)
        if path:
            self.app.notify("DBX Stats", f"Sensores exportados para {path.name}")
