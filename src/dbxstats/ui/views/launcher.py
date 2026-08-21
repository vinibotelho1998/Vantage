"""Biblioteca de jogos: arraste o .exe, escolha a tela, clique e jogue.

A ideia e' cortar o ritual de sempre — abrir Configuracoes do Windows, trocar a
primaria para a TV, achar o jogo, jogar, e no fim desfazer tudo na mao. Aqui o
atalho guarda o que fazer com as telas antes de abrir e devolve tudo sozinho
quando o jogo fecha.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from ... import theme
from ...core.session import resolve_shortcut
from ...platform import displays as D
from ...sensors import procs as P
from ..components import Badge, Card, PillButton, divider, label
from .base import View, scroll_page

_EXTS = (".exe", ".lnk", ".url", ".bat", ".cmd")


class DropZone(QWidget):
    """Area de arrastar e soltar. Aceita executavel e atalho."""

    def __init__(self, on_files) -> None:
        super().__init__()
        self._on_files = on_files
        self.setAcceptDrops(True)
        self.setFixedHeight(theme.scaled(104))
        lay = QVBoxLayout(self)
        lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.setSpacing(theme.scaled(2))
        self._title = label("Arraste um jogo aqui", 12, QFont.Weight.Bold, theme.MUTE)
        self._title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint = label(".exe, atalho .lnk ou .url — ou clique para procurar",
                     8.5, color=theme.FAINT)
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self._title)
        lay.addWidget(hint)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._paint(False)

    def _paint(self, hover: bool) -> None:
        cor = theme.FPS if hover else theme.LINE
        self.setStyleSheet(
            f"background: {theme.rgba(theme.FPS, 0.10 if hover else 0.0)};"
            f" border: 1px dashed {cor}; border-radius: {theme.scaled(10)}px;")

    def dragEnterEvent(self, event) -> None:
        if _paths_from(event.mimeData()):
            event.acceptProposedAction()
            self._paint(True)

    def dragLeaveEvent(self, event) -> None:
        self._paint(False)
        super().dragLeaveEvent(event)

    def dropEvent(self, event) -> None:
        self._paint(False)
        arquivos = _paths_from(event.mimeData())
        if arquivos:
            event.acceptProposedAction()
            self._on_files(arquivos)

    def mousePressEvent(self, event) -> None:
        escolhido, _ = QFileDialog.getOpenFileName(
            self, "Escolha o jogo", "",
            "Jogos e atalhos (*.exe *.lnk *.url *.bat *.cmd)")
        if escolhido:
            self._on_files([escolhido])


def _paths_from(mime) -> list[str]:
    if not mime.hasUrls():
        return []
    return [u.toLocalFile() for u in mime.urls()
            if u.isLocalFile() and u.toLocalFile().lower().endswith(_EXTS)]


_COMO_FUNCIONA = """Escolha em que tela o jogo abre — inclusive uma que esteja desligada.

Ao clicar em Jogar, o DBX Stats liga essa tela se preciso, coloca ela como principal,
abre o jogo e passa a acompanhar o processo. Quando o jogo fecha, as telas voltam
sozinhas para como estavam.

Os outros monitores continuam ligados o tempo todo: só muda quem manda."""


class LauncherView(View):
    key = "launcher"
    title = "Jogos"
    glyph = "▶"
    subtitle = "sua biblioteca: abre na tela certa, com um clique"

    def __init__(self, app) -> None:
        super().__init__(app)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(theme.scaled(theme.GAP))

        self.status = label("", 9, color=theme.MUTE)
        self.status.setVisible(False)
        root.addWidget(self.status)

        page, self.lay = scroll_page()
        root.addWidget(page, 1)

        barra = QHBoxLayout()
        barra.setSpacing(theme.scaled(8))
        self.btn_bp = PillButton("Abrir Big Picture", theme.FPS, filled=True)
        self.btn_bp.clicked.connect(self._abrir_big_picture)
        self.btn_bp.setToolTip("Tela cheia navegavel so' com o controle. "
                               "Também abre segurando Back por 1 s, ou com Ctrl+Alt+G.")
        barra.addWidget(self.btn_bp)
        barra.addStretch(1)
        self.lay.addLayout(barra)

        card_como = Card("Como funciona", theme.CPU)
        texto = label(_COMO_FUNCIONA, 9, color=theme.TXT)
        texto.setWordWrap(True)
        card_como.add(texto)
        # Mostrar o arranjo de agora e' o que torna a promessa verificavel: e'
        # exatamente para este estado que as telas voltam quando o jogo fecha.
        self.estado_telas = label("", 8.5, color=theme.MUTE)
        self.estado_telas.setWordWrap(True)
        card_como.add(self.estado_telas)
        self.lay.addWidget(card_como)

        card_drop = Card("Adicionar", theme.FPS,
                         "arraste o .exe ou o atalho do jogo para cá")
        card_drop.add(DropZone(self._add_files))
        self.lay.addWidget(card_drop)

        self.card_list = Card("Meus jogos", theme.DISK)
        self.items_box = QVBoxLayout()
        self.items_box.setSpacing(theme.scaled(8))
        self.card_list.add_layout(self.items_box)
        self.lay.addWidget(self.card_list)
        self.lay.addStretch(1)

        self._refresh()

    def _abrir_big_picture(self) -> None:
        abrir = getattr(self.app, "big_picture_abrir", None)
        if abrir is None:
            return
        try:
            abrir()
        except Exception as e:                                   # noqa: BLE001
            self.notify(f"não consegui abrir: {e}", theme.BAD)

    def _descrever_telas(self) -> str:
        """Uma linha dizendo como as telas estao agora."""
        try:
            telas = D.list_displays(with_modes=False)
        except Exception:                                    # noqa: BLE001
            return ""
        if not telas:
            return ""
        partes = []
        for d in telas:
            if d.primary:
                partes.append(f"{d.name} (principal)")
            elif d.active:
                partes.append(d.name)
            else:
                partes.append(f"{d.name} (desligada)")
        return "Ao fechar o jogo, volta para:  " + "   ·   ".join(partes)

    # ── dados ────────────────────────────────────────────────────────────────
    def _targets(self) -> list[tuple[str, str]]:
        """Opcoes de tela para o combo.

        So' telas. Perfil de tela saiu daqui: ele mexe na topologia inteira,
        apaga monitor que ninguem pediu para apagar e faz as tres telas piscarem
        por segundos. O atalho de jogo quer uma coisa so' — abrir naquela tela —
        e isso e' uma troca de primaria, que se desfaz sozinha no fim. Perfil
        continua existindo na aba Telas, para quem precisa mesmo dele.
        """
        opcoes = [("Não mexer nas telas", "")]
        for disp in D.list_displays(with_modes=False):
            if not disp.monitor_id:
                continue
            # Tela apagada continua na lista: a TV vive desligada e so' acorda
            # para jogar, entao ela e' justamente a escolha mais provavel aqui.
            if not disp.active:
                marca = " (desligada — liga ao abrir)"
            elif disp.primary:
                marca = " (já é a principal)"
            else:
                marca = ""
            opcoes.append((f"Abrir na {disp.name}{marca}", f"primary:{disp.monitor_id}"))
        return opcoes

    def _add_files(self, paths: list[str]) -> None:
        novos = 0
        itens = list(self.cfg.launch_items)
        for bruto in paths:
            alvo = resolve_shortcut(bruto)
            if any(i["path"].lower() == alvo.lower() for i in itens):
                continue
            itens.append({"name": Path(alvo).stem[:40], "path": alvo, "args": "",
                          "target": "", "restore": True})
            novos += 1
        if not novos:
            self.notify("esse jogo já está na lista", theme.WARN)
            return
        self.cfg.launch_items = itens
        self.cfg.save()
        self._refresh()
        self.notify(f"{novos} jogo(s) adicionado(s) — escolha a tela e jogue", theme.OK)

    def _save(self) -> None:
        self.cfg.save()

    def _remove(self, index: int) -> None:
        try:
            removido = self.cfg.launch_items.pop(index)
        except IndexError:
            return
        self._save()
        self._refresh()
        self.notify(f"'{removido['name']}' removido", theme.MUTE)

    # ── interface ────────────────────────────────────────────────────────────
    def on_activate(self) -> None:
        self._refresh()

    def _refresh(self) -> None:
        _clear(self.items_box)
        self.estado_telas.setText(self._descrever_telas())

        itens = self.cfg.launch_items
        if not itens:
            self.items_box.addWidget(
                label("nenhum jogo ainda — arraste um .exe aí em cima", 9,
                      color=theme.FAINT))
            return

        alvos = self._targets()
        for index, item in enumerate(itens):
            self.items_box.addWidget(self._build_row(index, item, alvos))
            if index < len(itens) - 1:
                self.items_box.addWidget(divider())

    def _build_row(self, index: int, item: dict, alvos: list[tuple[str, str]]) -> QWidget:
        holder = QWidget()
        col = QVBoxLayout(holder)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(theme.scaled(4))

        topo = QHBoxLayout()
        topo.setSpacing(theme.scaled(8))
        nome = QLineEdit(item["name"])
        nome.setMaximumWidth(theme.scaled(220))
        nome.editingFinished.connect(
            lambda i=index, w=nome: self._set(i, "name", w.text().strip()))
        topo.addWidget(nome)

        existe = Path(item["path"]).exists()
        topo.addWidget(Badge("pronto" if existe else "arquivo sumiu",
                             theme.OK if existe else theme.BAD))
        topo.addStretch(1)

        jogar = PillButton("Jogar", theme.FPS, filled=True)
        jogar.clicked.connect(lambda i=index: self._play(i))
        remover = PillButton("Remover", theme.BAD)
        remover.clicked.connect(lambda i=index: self._remove(i))
        topo.addWidget(jogar)
        topo.addWidget(remover)
        col.addLayout(topo)

        meio = QHBoxLayout()
        meio.setSpacing(theme.scaled(8))
        meio.addWidget(label("Ao abrir", 8.5, color=theme.MUTE))
        combo = QComboBox()
        for texto, valor in alvos:
            combo.addItem(texto, valor)
        atual = combo.findData(item.get("target", ""))
        combo.setCurrentIndex(max(0, atual))
        combo.currentIndexChanged.connect(
            lambda _i, idx=index, w=combo: self._set(idx, "target", w.currentData()))
        meio.addWidget(combo, 1)

        prio = QComboBox()
        prio.addItem("Prioridade normal", "")
        for opcao in P.PRIORIDADES:
            if opcao.chave == "normal":
                continue
            marca = " ⚠" if opcao.perigosa else ""
            prio.addItem(f"Prioridade {opcao.rotulo.lower()}{marca}", opcao.chave)
        prio.setCurrentIndex(max(0, prio.findData(item.get("priority", ""))))
        prio.setToolTip("Aplicada ao processo do jogo assim que ele é reconhecido. "
                        "Tempo real coloca o jogo à frente do próprio Windows e pode "
                        "travar a máquina — use com cuidado.")
        prio.currentIndexChanged.connect(
            lambda _i, idx=index, w=prio: self._set(idx, "priority", w.currentData()))
        meio.addWidget(prio)

        gravar = QCheckBox("gravar métricas da partida")
        gravar.setToolTip("Acompanha o jogo do início ao fim e guarda o resumo em "
                          "Benchmark › Sessões de jogo. Custa uma soma por quadro e "
                          "20 KB fixos — não cresce com a duração da partida.")
        gravar.setChecked(bool(item.get("bench", True)))
        gravar.toggled.connect(lambda on, i=index: self._set(i, "bench", bool(on)))
        meio.addWidget(gravar)

        bp = QCheckBox("voltar ao Big Picture quando o jogo fechar")
        bp.setToolTip("Em vez da janela normal, a grade de jogos reaparece na "
                      "tela onde você estava jogando. Quem está no sofá não "
                      "alcança o teclado para reabrir.")
        bp.setChecked(bool(item.get("voltar_bp", False)))
        bp.toggled.connect(lambda on, i=index: self._set(i, "voltar_bp", bool(on)))
        meio.addWidget(bp)

        voltar = QCheckBox("voltar ao normal quando o jogo fechar")
        voltar.setToolTip("O app acompanha o processo do jogo e desfaz a troca "
                          "sozinho quando ele fecha.")
        voltar.setChecked(bool(item.get("restore", True)))
        voltar.toggled.connect(lambda on, i=index: self._set(i, "restore", bool(on)))
        meio.addWidget(voltar)
        col.addLayout(meio)

        caminho = label(item["path"], 8, color=theme.FAINT)
        caminho.setToolTip(item["path"])
        col.addWidget(caminho)
        return holder

    def _set(self, index: int, key: str, value) -> None:
        try:
            self.cfg.launch_items[index][key] = value
        except IndexError:
            return
        self._save()

    def _play(self, index: int) -> None:
        try:
            item = self.cfg.launch_items[index]
        except IndexError:
            return
        ok, msg = self.app.play_item(item)
        self.notify(msg, theme.OK if ok else theme.BAD)

    def notify(self, text: str, color: str = theme.MUTE) -> None:
        self.status.setText(text)
        self.status.setStyleSheet(f"color: {color}; background: transparent;")
        self.status.setVisible(True)


def _clear(layout) -> None:
    # setParent(None) antes do deleteLater: a exclusao so' acontece na volta do
    # laco de eventos, e ate' la' o widget continuaria desenhado por cima do novo.
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget is not None:
            widget.setParent(None)
            widget.deleteLater()
        elif item.layout():
            _clear(item.layout())
