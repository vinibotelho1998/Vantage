"""Biblioteca de jogos: arraste o .exe, escolha a tela, clique e jogue.

A ideia e' cortar o ritual de sempre: abrir Configuracoes do Windows, trocar a
primaria para a TV, achar o jogo, jogar, e no fim desfazer tudo na mao. Aqui o
atalho guarda o que fazer com as telas antes de abrir e devolve tudo sozinho
quando o jogo fecha.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from ... import theme
from ...core.session import resolve_shortcut
from ...platform import art
from ...platform import displays as D
from ...platform import gamescan
from ...platform import win
from ...sensors import procs as P
from ..bigpicture import tempo_medido, ultima_sessao
from ..components import (Badge, Card, IconButton, PillButton, divider,
                          font, label)
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
        # Rodando como administrador, o Windows BLOQUEIA arrastar de um Explorer
        # comum para esta janela (UIPI) e nao avisa ninguem: o arquivo simplesmente
        # nao chega. Dizer isso aqui evita a conclusao de que o app "nao acha" o
        # jogo; e aponta os dois caminhos que funcionam.
        texto = (".exe, atalho .lnk ou .url, ou clique para procurar")
        if win.is_admin():
            texto = ("clique para procurar, arrastar não funciona com o app "
                     "como administrador")
        hint = label(texto, 8.5, color=theme.FAINT)
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
        # Abre na area de trabalho: e' de longe onde o jogo recem-baixado esta',
        # e o padrao anterior ("") caia na pasta de trabalho do processo, que com
        # o app elevado e' o System32, um lugar sem jogo nenhum dentro.
        inicio = os.path.expandvars(r"%USERPROFILE%\Desktop")
        escolhido, _ = QFileDialog.getOpenFileName(
            self, "Escolha o jogo", inicio if os.path.isdir(inicio) else "",
            # "Todos os arquivos" fica junto de proposito: um filtro que esconde
            # o arquivo que o usuario esta' vendo na pasta parece defeito do app.
            "Jogos e atalhos (*.exe *.lnk *.url *.bat *.cmd);;Todos os arquivos (*)")
        if escolhido:
            self._on_files([escolhido])


def _paths_from(mime) -> list[str]:
    if not mime.hasUrls():
        return []
    return [u.toLocalFile() for u in mime.urls()
            if u.isLocalFile() and u.toLocalFile().lower().endswith(_EXTS)]


_COMO_FUNCIONA = """Escolha em que tela o jogo abre, inclusive uma que esteja desligada.

Ao clicar em Jogar, o Vantage liga essa tela se preciso, coloca ela como principal,
abre o jogo e passa a acompanhar o processo. Quando o jogo fecha, as telas voltam
sozinhas para como estavam.

Os outros monitores continuam ligados o tempo todo: só muda quem manda."""


class Capa(QWidget):
    """Miniatura do jogo: a arte da capa, ou as iniciais quando nao ha' nenhuma.

    Nunca fica vazia. Um buraco na lista se le' como erro de carregamento, e a
    linha do jogo perde a ancora visual que faz a lista ser percorrivel de
    relance.
    """

    LARGURA = 132
    ALTURA = 74

    def __init__(self, item: dict, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._nome = item.get("name") or Path(item.get("path", "")).stem
        self.setFixedSize(theme.scaled(self.LARGURA), theme.scaled(self.ALTURA))
        try:
            caminho = art.artwork_path(item)
        except OSError:
            caminho = None
        self._pix = QPixmap(str(caminho)) if caminho is not None else QPixmap()

    def _iniciais(self) -> str:
        partes = [p for p in re.split(r"[\s\-_]+", self._nome) if p]
        return "".join(p[0] for p in partes[:2]).upper() or "?"

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(0, 0, -1, -1)
        raio = theme.scaled(8)
        caminho = QPainterPath()
        caminho.addRoundedRect(QRectF(rect), raio, raio)

        p.fillPath(caminho, QColor(theme.BG_SUNKEN))
        if not self._pix.isNull():
            p.save()
            p.setClipPath(caminho)
            quadrado = abs(self._pix.width() / max(1, self._pix.height()) - 1.0) < 0.15
            if quadrado:
                # Icone quadrado nao pode cobrir um retangulo deitado: ampliaria
                # varias vezes e cortaria o desenho. Cabe inteiro, centralizado.
                lado = int(rect.height() * 0.82)
                esc = self._pix.scaled(lado, lado, Qt.AspectRatioMode.KeepAspectRatio,
                                       Qt.TransformationMode.SmoothTransformation)
            else:
                esc = self._pix.scaled(rect.size(),
                                       Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                       Qt.TransformationMode.SmoothTransformation)
            p.drawPixmap(rect.x() + (rect.width() - esc.width()) // 2,
                         rect.y() + (rect.height() - esc.height()) // 2, esc)
            p.restore()
        else:
            p.setPen(QColor(theme.FAINT))
            p.setFont(font(15, QFont.Weight.Bold))
            p.drawText(rect, Qt.AlignmentFlag.AlignCenter, self._iniciais())

        p.setPen(QPen(QColor(theme.LINE_HI), 1))
        p.drawPath(caminho)
        p.end()


class EscolherJogos(QDialog):
    """Lista o que a varredura encontrou, para o usuario marcar o que quer.

    Adicionar tudo sozinho seria pior: a varredura acha ferramenta de biblioteca
    (Wallpaper Engine) junto com jogo, e uma lista que se enche sozinha de coisa
    errada custa mais para limpar do que para preencher.
    """

    def __init__(self, achados, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Jogos encontrados")
        self.setMinimumWidth(theme.scaled(620))
        self._caixas: list[tuple[QCheckBox, object]] = []

        col = QVBoxLayout(self)
        col.setContentsMargins(*(theme.scaled(16),) * 4)
        col.setSpacing(theme.scaled(10))
        col.addWidget(label(f"{len(achados)} encontrados fora da sua lista", 11,
                            QFont.Weight.Bold, theme.TXT))
        col.addWidget(label("desmarque o que não for jogo", 8.5, color=theme.FAINT))

        page, lista = scroll_page()
        col.addWidget(page, 1)
        for achado in achados:
            linha = QHBoxLayout()
            linha.setSpacing(theme.scaled(8))
            caixa = QCheckBox(achado.name)
            # Ja' marcado: o caso comum e' querer quase tudo, e desmarcar dois e'
            # menos trabalho que marcar dez.
            caixa.setChecked(True)
            linha.addWidget(caixa)
            linha.addWidget(Badge(achado.source, theme.CPU))
            linha.addStretch(1)
            caminho = label(achado.path, 7.5, color=theme.FAINT)
            caminho.setToolTip(achado.path)
            linha.addWidget(caminho)
            lista.addLayout(linha)
            self._caixas.append((caixa, achado))
        lista.addStretch(1)

        rodape = QHBoxLayout()
        rodape.setSpacing(theme.scaled(8))
        rodape.addStretch(1)
        cancelar = PillButton("Cancelar", theme.MUTE)
        cancelar.clicked.connect(self.reject)
        adicionar = PillButton("Adicionar selecionados", theme.FPS, filled=True)
        adicionar.clicked.connect(self.accept)
        rodape.addWidget(cancelar)
        rodape.addWidget(adicionar)
        col.addLayout(rodape)

    def escolhidos(self) -> list:
        return [achado for caixa, achado in self._caixas if caixa.isChecked()]


def _fmt_duracao(segundos: float) -> str:
    minutos = int(segundos // 60)
    if minutos < 60:
        return f"{minutos} min"
    return f"{minutos // 60} h {minutos % 60:02d} min"


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
        # A grade tambem escolhe em que tela abre, como qualquer jogo. Antes ela
        # nascia sempre na tela marcada para ficar apagada; servia para a TV da
        # sala, e quem quisesse a grade no monitor de cima nao tinha onde dizer.
        barra.addWidget(label("na tela", 8.5, color=theme.MUTE))
        self.bp_tela = QComboBox()
        self.bp_tela.setMinimumWidth(theme.scaled(210))
        barra.addWidget(self.bp_tela)
        self.btn_scan = PillButton("Procurar jogos instalados", theme.GPU)
        self.btn_scan.clicked.connect(self._procurar)
        self.btn_scan.setToolTip("Varre o Steam e as pastas de jogos dos seus discos.")
        barra.addWidget(self.btn_scan)
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

    def _procurar(self) -> None:
        """Varre os discos e oferece o que achou."""
        self.notify("procurando jogos…", theme.MUTE)
        try:
            achados = gamescan.scan([i["path"] for i in self.cfg.launch_items])
        except Exception as e:                                   # noqa: BLE001
            self.notify(f"a varredura falhou: {e}", theme.BAD)
            return
        if not achados:
            self.notify("nenhum jogo novo encontrado", theme.WARN)
            return
        dialogo = EscolherJogos(achados, self)
        if dialogo.exec() != QDialog.DialogCode.Accepted:
            return
        escolhidos = dialogo.escolhidos()
        if not escolhidos:
            return
        itens = list(self.cfg.launch_items)
        for achado in escolhidos:
            itens.append({"name": achado.name, "path": achado.path, "args": "",
                          "target": "", "restore": True})
        self.cfg.launch_items = itens
        self.cfg.save()
        self._refresh()
        self.notify(f"{len(escolhidos)} jogo(s) adicionado(s)", theme.OK)

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

    def _targets(self) -> list[tuple[str, str]]:
        """Opcoes de tela para o combo.

        So' telas. Perfil de tela saiu daqui: ele mexe na topologia inteira,
        apaga monitor que ninguem pediu para apagar e faz as tres telas piscarem
        por segundos. O atalho de jogo quer uma coisa so' (abrir naquela tela)
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
                marca = " (desligada, liga ao abrir)"
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
        self.notify(f"{novos} jogo(s) adicionado(s); escolha a tela e jogue", theme.OK)

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

    def on_activate(self) -> None:
        self._refresh()

    def _encher_tela_bp(self, alvos: list[tuple[str, str]]) -> None:
        """Reaproveita a lista de telas dos jogos, trocando so' o prefixo.

        O Big Picture nao troca a primaria (quem manda continua sendo assunto do
        atalho de cada jogo), entao o valor sai como `screen:` e nao `primary:`.
        """
        atual = str(getattr(self.cfg, "bigpicture_target", "") or "")
        self.bp_tela.blockSignals(True)
        self.bp_tela.clear()
        self.bp_tela.addItem("como está (segue a TV de jogo)", "")
        for texto, valor in alvos:
            if not valor.startswith("primary:"):
                continue
            monitor = valor.split(":", 1)[1]
            rotulo = texto.replace("Abrir na ", "").replace(" (já é a principal)", "")
            self.bp_tela.addItem(f"Abrir na {rotulo}", f"screen:{monitor}")
        indice = self.bp_tela.findData(atual)
        self.bp_tela.setCurrentIndex(max(0, indice))
        self.bp_tela.blockSignals(False)
        try:
            self.bp_tela.currentIndexChanged.disconnect()
        except (RuntimeError, TypeError):
            pass
        self.bp_tela.currentIndexChanged.connect(self._trocar_tela_bp)

    def _trocar_tela_bp(self) -> None:
        self.cfg.bigpicture_target = self.bp_tela.currentData() or ""
        self.cfg.save()

    def _refresh(self) -> None:
        _clear(self.items_box)
        self.estado_telas.setText(self._descrever_telas())
        # Antes da saida antecipada de lista vazia: a grade tem tela propria
        # mesmo sem jogo nenhum cadastrado.
        self._encher_tela_bp(self._targets())

        itens = self.cfg.launch_items
        if not itens:
            self.items_box.addWidget(
                label("nenhum jogo ainda, arraste um .exe aí em cima", 9,
                      color=theme.FAINT))
            return

        alvos = self._targets()
        for index, item in enumerate(itens):
            self.items_box.addWidget(self._build_row(index, item, alvos))
            if index < len(itens) - 1:
                self.items_box.addWidget(divider())

    def _build_row(self, index: int, item: dict, alvos: list[tuple[str, str]]) -> QWidget:
        holder = QWidget()
        raiz = QHBoxLayout(holder)
        raiz.setContentsMargins(0, 0, 0, 0)
        raiz.setSpacing(theme.scaled(12))

        # A capa vem primeiro e manda no reconhecimento: numa lista de dez jogos,
        # o olho acha a arte antes de ler qualquer nome.
        raiz.addWidget(Capa(item), 0, Qt.AlignmentFlag.AlignTop)

        col = QVBoxLayout()
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(theme.scaled(4))
        raiz.addLayout(col, 1)

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
        topo.addWidget(jogar)
        mais = IconButton("⋯", "ajustes deste jogo")
        topo.addWidget(mais)
        col.addLayout(topo)

        col.addLayout(self._faixa_de_desempenho(item))

        # Tudo daqui para baixo e' ajuste: escolhe-se uma vez por jogo e nao se
        # olha mais. Ficava tudo aberto ao mesmo tempo, e cinco jogos viravam uma
        # parede de seletor e caixa de marcar onde a capa e o fps sumiam.
        ajustes = QWidget()
        ajustes.setVisible(False)
        ajustes_col = QVBoxLayout(ajustes)
        ajustes_col.setContentsMargins(0, theme.scaled(4), 0, 0)
        ajustes_col.setSpacing(theme.scaled(4))
        mais.clicked.connect(
            lambda w=ajustes, b=mais: (w.setVisible(not w.isVisible()),
                                       b.setText("×" if w.isVisible() else "⋯")))

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
                        "travar a máquina, use com cuidado.")
        prio.currentIndexChanged.connect(
            lambda _i, idx=index, w=prio: self._set(idx, "priority", w.currentData()))
        meio.addWidget(prio)

        gravar = QCheckBox("gravar métricas da partida")
        gravar.setToolTip("Acompanha o jogo do início ao fim e guarda o resumo em "
                          "Benchmark › Sessões de jogo. Custa uma soma por quadro e "
                          "20 KB fixos; não cresce com a duração da partida.")
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
        ajustes_col.addLayout(meio)

        rodape = QHBoxLayout()
        rodape.setSpacing(theme.scaled(8))
        remover = PillButton("Remover", theme.BAD)
        remover.clicked.connect(lambda i=index: self._remove(i))
        caminho = label(item["path"], 8, color=theme.FAINT)
        caminho.setToolTip(item["path"])
        rodape.addWidget(caminho, 1)

        origem = art.origin(item)
        rodape.addWidget(label(art.ORIGIN_LABEL[origem], 8,
                               color=theme.MUTE if origem in ("escolhida", "steam")
                               else theme.FAINT))
        capa = PillButton("Trocar capa" if origem == "escolhida" else "Escolher capa",
                          theme.MUTE)
        capa.clicked.connect(lambda i=index: self._escolher_capa(i))
        rodape.addWidget(capa)
        if origem == "escolhida":
            auto = PillButton("Usar automática", theme.FAINT)
            auto.clicked.connect(lambda i=index: self._trocar_capa(i, ""))
            rodape.addWidget(auto)
        rodape.addWidget(remover)
        ajustes_col.addLayout(rodape)
        col.addWidget(ajustes)
        return holder

    def _faixa_de_desempenho(self, item: dict) -> QHBoxLayout:
        """O que a maquina fez da ultima vez que rodou este jogo.

        Vem do historico ja' gravado pelo proprio app; nada aqui e' medido de
        novo. E' a informacao que decide se vale mexer em ajuste antes de jogar,
        e ate' agora ela so' existia enterrada na aba Benchmark.
        """
        linha = QHBoxLayout()
        linha.setSpacing(theme.scaled(14))
        historico = getattr(self.app, "session_history", None) or []
        nome = item.get("name") or Path(item.get("path", "")).stem
        ultima = ultima_sessao(historico, nome)

        if ultima is None:
            linha.addWidget(label("sem partida gravada ainda", 8.5, color=theme.FAINT))
            linha.addStretch(1)
            return linha

        def par(rotulo: str, valor: str, cor: str) -> None:
            caixa = QVBoxLayout()
            caixa.setSpacing(0)
            caixa.addWidget(label(valor, 11, QFont.Weight.Bold, cor))
            caixa.addWidget(label(rotulo, 7.5, color=theme.FAINT))
            linha.addLayout(caixa)

        media = ultima.get("fps_avg")
        if media:
            par("fps médio", f"{float(media):.0f}", theme.FPS)
        low = ultima.get("low_1")
        if low:
            # O 1% low e' o numero que explica engasgo; a media sozinha esconde
            # exatamente o que incomoda jogando.
            par("1% low", f"{float(low):.0f}", theme.FRAME)
        stutter = ultima.get("stutter_pct")
        if stutter is not None:
            par("engasgo", f"{float(stutter):.1f}%",
                theme.OK if float(stutter) < 2 else theme.WARN)

        total = tempo_medido(historico, nome)
        if total:
            par("medido", _fmt_duracao(total), theme.MUTE)

        partidas = sum(1 for r in historico
                       if str(r.get("game", "")).strip().lower() == nome.strip().lower())
        if partidas:
            par("partidas", str(partidas), theme.MUTE)

        linha.addStretch(1)
        quando = str(ultima.get("quando", ""))[:16].replace("T", " ")
        if quando:
            linha.addWidget(label(f"última: {quando}", 8, color=theme.FAINT))
        return linha

    def _escolher_capa(self, index: int) -> None:
        try:
            item = self.cfg.launch_items[index]
        except IndexError:
            return
        arquivo, _ = QFileDialog.getOpenFileName(
            self, f"Capa de {item.get('name', 'jogo')}",
            str(Path(item.get("image", "") or item.get("path", "")).parent),
            "Imagens (*.png *.jpg *.jpeg *.webp *.bmp)")
        if arquivo:
            self._trocar_capa(index, arquivo)

    def _trocar_capa(self, index: int, caminho: str) -> None:
        """Grava a capa e redesenha a lista, para o rotulo de origem acompanhar."""
        self._set(index, "image", caminho)
        self._refresh()

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
