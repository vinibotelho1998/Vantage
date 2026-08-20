"""Atalhos de jogo: arraste o .exe, escolha a tela, clique e jogue.

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


class LauncherView(View):
    key = "launcher"
    title = "Atalhos"
    glyph = "▶"
    subtitle = "abre o jogo já na tela certa"

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

        card_drop = Card("Adicionar", theme.FPS,
                         "o atalho guarda a tela; o jogo abre já do jeito certo")
        card_drop.add(DropZone(self._add_files))
        self.lay.addWidget(card_drop)

        self.card_list = Card("Meus jogos", theme.DISK)
        self.items_box = QVBoxLayout()
        self.items_box.setSpacing(theme.scaled(8))
        self.card_list.add_layout(self.items_box)
        self.lay.addWidget(self.card_list)
        self.lay.addStretch(1)

        self._refresh()

    # ── dados ────────────────────────────────────────────────────────────────
    def _targets(self) -> list[tuple[str, str]]:
        """Opcoes de tela para o combo.

        Trocar a principal vem antes dos perfis de proposito: e' a acao que o
        atalho de jogo quer quase sempre ("abre na TV"), custa uma chamada so' e
        se desfaz sozinha no fim. Perfil mexe na topologia inteira e faz as telas
        apagarem por segundos — util quando e' mesmo o caso, exagero como padrao.
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
        for profile in self.cfg.display_profiles:
            opcoes.append((f"Aplicar o perfil '{profile['name']}'",
                           f"profile:{profile['name']}"))
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
