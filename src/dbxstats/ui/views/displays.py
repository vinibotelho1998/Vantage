"""Tela de gerenciamento de monitores: modo, ligar e desligar, primaria e perfis.

Fala direto com `platform.displays`, que usa API nativa do Windows. Duas decisoes
desta tela vieram de problema real e valem registro:

Desligar aqui e' desanexar do desktop. Nunca desabilitar o dispositivo no
Gerenciador de Dispositivos: aquilo mantem a saida de video viva com o no de
monitor em erro, e o app de Configuracoes do Windows para de abrir.

A lista de modos vem do driver, nao do EDID. Algumas TVs declaram menos blocos de
extensao do que realmente possuem, e o Windows para de ler antes das taxas altas.
E' por isso que 4K 144 aparece aqui mesmo quando some das Configuracoes.
"""
from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from ... import theme
from ...platform import ccd
from ...platform import displays as D
from ...platform import win as winapi
from ..components import Badge, Card, KpiStrip, PillButton, divider, label
from ..confirm import confirm_or_revert as ask_confirm
from .base import View, scroll_page

_KPIS = [
    ("total", "Telas", ""), ("on", "Ligadas", ""),
    ("primary", "Primária", ""), ("pixels", "Área total", "px"),
]


def _index_of(box: QComboBox, value) -> int:
    """Indice do item com esse valor, comparando por igualdade.

    QComboBox.findData nao serve aqui: com payload Python opaco — uma tupla
    (largura, altura) — ele compara por identidade, entao procurar (1920, 1080)
    devolvia -1 mesmo com o item guardando exatamente (1920, 1080). O seletor
    ficava parado no primeiro item, que e' o maior modo da lista: numa TV 4K
    isso mostrava "4096 x 2160 escalonada" com a tela em 3840 x 2160 nativo, e
    aplicar sem perceber jogava o painel para um modo esticado.
    """
    for i in range(box.count()):
        if box.itemData(i) == value:
            return i
    return -1


def _combo(items: list[tuple[str, object]], current=None) -> QComboBox:
    box = QComboBox()
    for text, value in items:
        box.addItem(text, value)
    if current is not None:
        idx = _index_of(box, current)
        if idx >= 0:
            box.setCurrentIndex(idx)
    return box


_SNAP = 40
"""Distancia, em pixels do desktop virtual, para colar uma tela na outra."""


class ArrangeCanvas(QWidget):
    """Mapa arrastavel das telas ligadas.

    O Windows nao aceita buraco nem sobreposicao no desktop virtual, entao soltar
    a tela em qualquer lugar produziria uma configuracao recusada. Por isso o
    arraste cola nas bordas das vizinhas assim que chega perto.
    """

    moved = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(theme.scaled(180))
        self.setMouseTracking(True)
        self.rects: dict[str, QRect] = {}
        self.names: dict[str, str] = {}
        self.primary: str = ""
        self._drag: str | None = None
        self._grab = QPoint()
        self.apagadas: set[str] = set()
        """Telas conectadas e fora da area de trabalho; ver load."""
        self._proj: tuple[QRect, float, float, float] | None = None
        """Projecao congelada durante o arraste; ver _projection."""

    def load(self, displays: list[D.Display]) -> None:
        """Monta o mapa com TODAS as telas conectadas, ligadas ou nao.

        Antes as apagadas simplesmente sumiam daqui, e sumir e' ambiguo: ninguem
        sabe se a tela esta' desligada, desconectada ou se o app nao a viu. Elas
        aparecem em posicao propria, com contorno tracejado e o rotulo dizendo
        que estao desligadas.
        """
        self.rects.clear()
        self.names.clear()
        self.apagadas.clear()
        ligadas = [d for d in displays if d.active and d.mode]
        for disp in ligadas:
            self.rects[disp.monitor_id] = QRect(disp.position[0], disp.position[1],
                                                disp.mode.width, disp.mode.height)
            self.names[disp.monitor_id] = disp.name
            if disp.primary:
                self.primary = disp.monitor_id

        # A apagada nao tem posicao no desktop — o Windows nao guarda uma para
        # quem esta' fora dele. Entao ela e' encostada a direita do conjunto, so'
        # para existir no mapa; arrastar continua valendo so' para as ligadas.
        borda = max((r.right() for r in self.rects.values()), default=0)
        topo = min((r.top() for r in self.rects.values()), default=0)
        for disp in displays:
            if disp.active or not disp.monitor_id:
                continue
            largura, altura = (disp.native or (1920, 1080))
            borda += int(largura * 0.12)
            self.rects[disp.monitor_id] = QRect(borda, topo, largura, altura)
            self.names[disp.monitor_id] = disp.name
            self.apagadas.add(disp.monitor_id)
            borda += largura
        self.update()

    # ── conversao de coordenadas ─────────────────────────────────────────────
    def _bounds(self) -> QRect:
        if not self.rects:
            return QRect(0, 0, 1, 1)
        todos = list(self.rects.values())
        left = min(r.left() for r in todos)
        top = min(r.top() for r in todos)
        right = max(r.right() for r in todos)
        bottom = max(r.bottom() for r in todos)
        return QRect(left, top, right - left, bottom - top)

    def _scale(self) -> float:
        b = self._bounds()
        margem = theme.scaled(16)
        return min((self.width() - margem * 2) / max(1, b.width()),
                   (self.height() - margem * 2) / max(1, b.height()))

    def _projection(self) -> tuple[QRect, float, float, float]:
        """Limites, escala e deslocamento usados para desenhar.

        Durante o arraste devolve o que foi congelado no clique. Recalcular a
        cada movimento criava um laco: afastar uma tela aumentava os limites, a
        escala encolhia, tudo era redesenhado menor e o retangulo fugia do
        cursor encolhendo, ate' parecer que tinha sumido.
        """
        if self._proj is not None:
            return self._proj
        b, s = self._bounds(), self._scale()
        return b, s, (self.width() - b.width() * s) / 2, (self.height() - b.height() * s) / 2

    def _to_screen(self, r: QRect) -> QRect:
        b, s, ox, oy = self._projection()
        return QRect(int(ox + (r.left() - b.left()) * s), int(oy + (r.top() - b.top()) * s),
                     max(2, int(r.width() * s)), max(2, int(r.height() * s)))

    def _to_desktop(self, ponto: QPoint) -> QPoint:
        """Ponto do widget de volta em coordenadas de area de trabalho."""
        b, s, ox, oy = self._projection()
        s = s or 1
        return QPoint(int(b.left() + (ponto.x() - ox) / s),
                      int(b.top() + (ponto.y() - oy) / s))

    # ── arraste ──────────────────────────────────────────────────────────────
    def mousePressEvent(self, event) -> None:
        ponto = event.position().toPoint()
        for key, rect in reversed(list(self.rects.items())):
            if key in self.apagadas:
                continue          # sem posicao real no desktop, nada a arrastar
            if not self._to_screen(rect).contains(ponto):
                continue
            self._drag = key
            # Congela a projecao pelo arraste inteiro: e' o que mantem a tela
            # embaixo do cursor enquanto ela se afasta das outras.
            b, s = self._bounds(), self._scale()
            self._proj = (b, s, (self.width() - b.width() * s) / 2,
                          (self.height() - b.height() * s) / 2)
            # Guarda onde dentro da tela o clique caiu. Somar deltas a cada
            # movimento acumulava o erro do arredondamento e a tela ia escapando
            # do ponteiro aos poucos.
            self._grab = self._to_desktop(ponto) - rect.topLeft()
            return

    def mouseMoveEvent(self, event) -> None:
        if self._drag is None:
            return
        rect = self.rects[self._drag]
        destino = self._to_desktop(event.position().toPoint()) - self._grab
        rect.moveTo(destino)
        self._snap(self._drag)
        self.update()

    def mouseReleaseEvent(self, event) -> None:
        if self._drag is not None:
            self._drag = None
            self._proj = None
            self._normalize()
            self.moved.emit()
            self.update()

    def _snap(self, key: str) -> None:
        alvo = self.rects[key]
        for outro, rect in self.rects.items():
            if outro == key:
                continue
            for meu, dele in ((alvo.left(), rect.right() + 1), (alvo.right() + 1, rect.left()),
                              (alvo.left(), rect.left()), (alvo.right(), rect.right())):
                if abs(meu - dele) <= _SNAP:
                    alvo.translate(dele - meu, 0)
                    break
            for meu, dele in ((alvo.top(), rect.bottom() + 1), (alvo.bottom() + 1, rect.top()),
                              (alvo.top(), rect.top()), (alvo.bottom(), rect.bottom())):
                if abs(meu - dele) <= _SNAP:
                    alvo.translate(0, dele - meu)
                    break

    def _normalize(self) -> None:
        """A primaria manda em (0,0), entao todo o conjunto anda junto ate' la'."""
        ancora = self.rects.get(self.primary)
        if ancora is None:
            return
        dx, dy = ancora.left(), ancora.top()
        if (dx, dy) == (0, 0):
            return
        for rect in self.rects.values():
            rect.translate(-dx, -dy)

    def positions(self) -> dict[str, tuple[int, int]]:
        # A posicao das apagadas e' so' de desenho: mandar isso para o Windows
        # inventaria um arranjo que ninguem pediu.
        return {k: (r.left(), r.top()) for k, r in self.rects.items()
                if k not in self.apagadas}

    # ── pintura ──────────────────────────────────────────────────────────────
    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        for key, rect in self.rects.items():
            box = self._to_screen(rect)
            apagada = key in self.apagadas
            principal = key == self.primary and not apagada
            cor = QColor(theme.RAM if principal else theme.FPS)
            if apagada:
                # Tracejado e cor apagada: a tela existe, esta' conectada, e nao
                # esta' na area de trabalho. As tres coisas de relance.
                cor = QColor(theme.FAINT)
            p.setBrush(QBrush(QColor(theme.BG if apagada else theme.SURFACE)))
            caneta = QPen(cor, 2)
            if apagada:
                caneta.setStyle(Qt.PenStyle.DashLine)
            p.setPen(caneta)
            p.drawRoundedRect(box, 6, 6)
            # Cada linha ganha faixa propria a partir do centro. Centralizar as
            # duas na mesma caixa imprimia uma por cima da outra.
            meio = box.center().y()
            linha = theme.scaled(15)
            p.setPen(QPen(QColor(theme.MUTE if apagada else theme.TXT), 1))
            p.setFont(QFont(theme.FONT_UI, 8, QFont.Weight.DemiBold))
            p.drawText(QRect(box.x(), meio - linha, box.width(), linha),
                       Qt.AlignmentFlag.AlignCenter, self.names.get(key, ""))
            p.setPen(QPen(QColor(theme.FAINT), 1))
            p.setFont(QFont(theme.FONT_UI, 7))
            p.drawText(QRect(box.x(), meio + 1, box.width(), linha),
                       Qt.AlignmentFlag.AlignCenter,
                       f"{rect.width()} x {rect.height()}")
            rodape, cor_rodape = "", theme.RAM
            if apagada:
                rodape, cor_rodape = "desligada", theme.FAINT
            elif principal:
                rodape = "primária"
            if rodape:
                p.setPen(QPen(QColor(cor_rodape), 1))
                p.drawText(QRect(box.x(), box.bottom() - linha - 4, box.width(), linha),
                           Qt.AlignmentFlag.AlignCenter, rodape)
        p.end()


class _DisplayCard(Card):
    """Um cartao por tela fisica, com os controles dela."""

    changed = Signal()

    def __init__(self, disp: D.Display, view: DisplaysView) -> None:
        color = theme.GPU if disp.active else theme.FAINT
        super().__init__(disp.name or disp.device, color)
        self.view = view
        self.disp = disp

        self.badge = Badge("", theme.MUTE)
        self.add_header_widget(self.badge)

        info = QHBoxLayout()
        info.setSpacing(theme.scaled(14))
        nativa = f"{disp.native[0]} x {disp.native[1]}" if disp.native else "?"
        for caption, value in (("Nativa", nativa), ("Atual", disp.summary),
                               ("Saída", disp.device.replace("\\\\.\\", ""))):
            cell = QVBoxLayout()
            cell.setSpacing(0)
            cell.addWidget(label(caption.upper(), 7.5, color=theme.FAINT))
            cell.addWidget(label(value, 9.5, color=theme.TXT))
            info.addLayout(cell)
        info.addStretch(1)
        self.add_layout(info)
        self.add(divider())

        # A nativa e' o padrao quando nao da' para casar com o modo atual. Deixar
        # o seletor no primeiro item significaria oferecer a maior resolucao da
        # lista, que costuma ser escalonada.
        inicial = None
        if self.disp.mode:
            inicial = (self.disp.mode.width, self.disp.mode.height)
        elif self.disp.native:
            inicial = tuple(self.disp.native)
        self.res_box = _combo(self._resolutions(), inicial)
        self.hz_box = _combo([])
        self.res_box.currentIndexChanged.connect(self._fill_rates)
        self._fill_rates()

        row = QHBoxLayout()
        row.setSpacing(theme.scaled(8))
        row.addWidget(label("Resolução", 8.5, color=theme.MUTE))
        row.addWidget(self.res_box, 2)
        row.addWidget(label("Taxa", 8.5, color=theme.MUTE))
        row.addWidget(self.hz_box, 1)
        self.add_layout(row)

        self.rot_box = _combo([(nome, valor) for valor, nome in D.ROTATIONS],
                              disp.rotation)
        self.rot_box.currentIndexChanged.connect(self._rotate)
        row.addWidget(label("Giro", 8.5, color=theme.MUTE))
        row.addWidget(self.rot_box, 1)

        actions = QHBoxLayout()
        actions.setSpacing(theme.scaled(8))
        self.btn_apply = PillButton("Aplicar", theme.FPS, filled=True)
        self.btn_apply.clicked.connect(self._apply_mode)
        self.btn_primary = PillButton("Tornar primária", theme.RAM)
        self.btn_primary.clicked.connect(self._make_primary)
        self.btn_windows = PillButton("Trazer janelas", theme.CPU)
        self.btn_windows.clicked.connect(self._pull_windows)
        self.btn_power = PillButton("", theme.MUTE)
        self.btn_power.clicked.connect(self._toggle_power)
        self.btn_mirror = PillButton("Espelhar nesta", theme.DISK)
        self.btn_mirror.clicked.connect(self._save_mirror)
        self.btn_default = PillButton("", theme.OK)
        self.btn_default.clicked.connect(self._set_default_primary)
        self.btn_off_default = PillButton("", theme.MUTE)
        self.btn_off_default.clicked.connect(self._toggle_off_by_default)
        actions.addWidget(self.btn_apply)
        actions.addWidget(self.btn_primary)
        actions.addWidget(self.btn_default)
        actions.addWidget(self.btn_off_default)
        actions.addWidget(self.btn_windows)
        actions.addWidget(self.btn_mirror)
        actions.addWidget(self.btn_power)
        actions.addStretch(1)
        self.add_layout(actions)

        self._sync_state()

    # ── dados ────────────────────────────────────────────────────────────────
    def _resolutions(self) -> list[tuple[str, object]]:
        seen: dict[tuple[int, int], bool] = {}
        for mode in self.disp.modes:
            key = (mode.width, mode.height)
            if key not in seen:
                seen[key] = self.disp.is_upscaled(mode)
        items = []
        for (w, h), upscaled in sorted(seen.items(), key=lambda kv: kv[0][0] * kv[0][1],
                                       reverse=True):
            suffix = ""
            if self.disp.native and (w, h) == tuple(self.disp.native):
                suffix = "   nativa"
            elif upscaled:
                suffix = "   escalonada"
            items.append((f"{w} x {h}{suffix}", (w, h)))
        return items

    def _fill_rates(self) -> None:
        key = self.res_box.currentData()
        self.hz_box.clear()
        if not key:
            return
        rates = sorted({m.refresh for m in self.disp.modes
                        if (m.width, m.height) == key}, reverse=True)
        for hz in rates:
            self.hz_box.addItem(f"{hz} Hz", hz)

    def _selected(self) -> D.Mode | None:
        size = self.res_box.currentData()
        hz = self.hz_box.currentData()
        if not size or not hz:
            return None
        return D.Mode(size[0], size[1], hz)

    def _sync_state(self) -> None:
        padrao = self.view.cfg.display_primary_default == self.disp.monitor_id
        self.btn_default.setText("Não ser a principal padrão" if padrao
                                 else "Ser a principal padrão")
        self.btn_default.set_color(theme.MUTE if padrao else theme.OK)
        self.btn_default.setVisible(self.disp.active)
        apagada_por_padrao = self.disp.monitor_id in self.view.cfg.display_off_by_default
        self.btn_off_default.setText("Não nascer apagada" if apagada_por_padrao
                                     else "Nascer apagada")
        self.btn_off_default.set_color(theme.MUTE if apagada_por_padrao else theme.DISK)
        # Uma tela nao pode ser a principal padrao e nascer apagada ao mesmo tempo.
        self.btn_off_default.setVisible(not padrao)
        if self.disp.primary and padrao:
            self.badge.update_badge("PRIMÁRIA · PADRÃO", theme.OK)
        elif self.disp.primary:
            self.badge.update_badge("PRIMÁRIA", theme.RAM)
        elif padrao:
            self.badge.update_badge("padrão", theme.OK)
        elif self.disp.monitor_id in self.view.cfg.display_off_by_default:
            self.badge.update_badge("apagada por padrão" if not self.disp.active
                                    else "ligada · apaga por padrão", theme.DISK)
        elif self.disp.active:
            self.badge.update_badge("ligada", theme.OK)
        else:
            self.badge.update_badge("desligada", theme.FAINT)
        self.btn_power.setText("Desligar" if self.disp.active else "Ligar")
        self.btn_power.set_color(theme.BAD if self.disp.active else theme.OK)
        self.btn_primary.setVisible(self.disp.active and not self.disp.primary)
        self.btn_apply.setVisible(self.disp.active)
        self.res_box.setEnabled(self.disp.active)
        self.hz_box.setEnabled(self.disp.active)

        if self.disp.active and self.disp.mode:
            idx = _index_of(self.res_box, (self.disp.mode.width, self.disp.mode.height))
            if idx >= 0 and idx != self.res_box.currentIndex():
                self.res_box.setCurrentIndex(idx)
                self._fill_rates()
            idx = _index_of(self.hz_box, self.disp.mode.refresh)
            if idx >= 0:
                self.hz_box.setCurrentIndex(idx)

    # ── acoes ────────────────────────────────────────────────────────────────
    def _apply_mode(self) -> None:
        mode = self._selected()
        if mode is None:
            return
        previous = self.disp.mode
        device = self.disp.device
        ok, err = D.set_mode(device, mode)
        if not ok:
            self.view.notify(f"{self.disp.name}: {err}", theme.BAD)
            return
        if previous is None:
            self.view.reload()
            return
        self.view.confirm_or_revert(f"{self.disp.name} em {mode.label}",
                                    lambda: D.set_mode(device, previous))

    def _rotate(self) -> None:
        alvo = self.rot_box.currentData()
        if alvo is None or alvo == self.disp.rotation:
            return
        previous = self.disp.rotation
        device = self.disp.device
        ok, err = D.set_rotation(device, alvo)
        if not ok:
            self.view.notify(f"{self.disp.name}: {err}", theme.BAD)
            self.view.reload()
            return
        self.view.confirm_or_revert(f"{self.disp.name} girada",
                                    lambda: D.set_rotation(device, previous))

    def _pull_windows(self) -> None:
        if not self.disp.active or not self.disp.mode:
            return
        x, y = self.disp.position
        quantas = winapi.move_windows_to(
            (x, y, x + self.disp.mode.width, y + self.disp.mode.height))
        self.view.notify(f"{quantas} janela(s) trazidas para {self.disp.name}",
                         theme.OK if quantas else theme.WARN)

    def _save_mirror(self) -> None:
        """Guarda um perfil de espelho ancorado nesta tela.

        Ancorar e' escolha do usuario de proposito: a TV costuma estar desligada
        justamente na hora de montar o perfil, e adivinhar pelo tamanho acaba
        elegendo o monitor da mesa.
        """
        self.view.save_mirror_profile(self.disp)

    def _make_primary(self) -> None:
        ok, err = D.set_primary(self.disp.device)
        self.view.notify(f"{self.disp.name} agora é a primária" if ok
                         else f"{self.disp.name}: {err}", theme.OK if ok else theme.BAD)
        self.view.reload()

    def _set_default_primary(self) -> None:
        """Marca (ou desmarca) esta tela como a principal da casa.

        Diferente de "Tornar primaria", que vale so' agora: esta escolha e'
        reimposta quando um monitor e' conectado, quando um jogo fecha e quando
        o app abre. Sem ela, plugar a TV entrega a primaria a ela — o Windows
        promove sozinho a tela que acabou de chegar — e a barra de tarefas some
        para um canto onde ninguem esta'.
        """
        cfg = self.view.cfg
        ja_era = cfg.display_primary_default == self.disp.monitor_id
        cfg.display_primary_default = "" if ja_era else self.disp.monitor_id
        cfg.save()
        if not ja_era:
            D.set_primary(self.disp.device)
            self.view.notify(f"{self.disp.name} agora é a principal padrão", theme.OK)
        else:
            self.view.notify(f"{self.disp.name} deixou de ser a principal padrão",
                             theme.MUTE)
        self.view.reload()

    def _toggle_off_by_default(self) -> None:
        """Esta tela nasce apagada, mesmo conectada.

        E' o arranjo da TV da sala: plugada e reconhecida o tempo todo, fora da
        area de trabalho ate' um atalho de jogo pedir por ela. Sem isso o
        Windows acende a tela assim que a detecta.
        """
        cfg = self.view.cfg
        lista = list(cfg.display_off_by_default)
        ja_era = self.disp.monitor_id in lista
        if ja_era:
            lista.remove(self.disp.monitor_id)
        else:
            lista.append(self.disp.monitor_id)
        cfg.display_off_by_default = lista
        cfg.save()
        self.view.notify(
            f"{self.disp.name} volta a acompanhar o Windows" if ja_era
            else f"{self.disp.name} vai nascer apagada; um atalho de jogo acende",
            theme.MUTE if ja_era else theme.OK)
        self.view.reload()

    def _toggle_power(self) -> None:
        target = not self.disp.active
        device = self.disp.device
        before = D.snapshot()
        ok, err = D.set_enabled(device, target)
        if not ok:
            self.view.notify(f"{self.disp.name}: {err}", theme.BAD)
            self.view.reload()
            return
        self.view.confirm_or_revert(
            f"{self.disp.name} {'ligada' if target else 'desligada'}",
            lambda: D.apply_profile(before))


class DisplaysView(View):
    key = "displays"
    title = "Telas"
    glyph = "▣"
    subtitle = "monitores, modos e perfis"

    def __init__(self, app) -> None:
        super().__init__(app)
        self._cards: list[_DisplayCard] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(theme.scaled(theme.GAP))

        self.kpi = KpiStrip(_KPIS, columns=5)
        root.addWidget(self.kpi)

        self.status = label("", 9, color=theme.MUTE)
        self.status.setVisible(False)
        root.addWidget(self.status)

        page, self.lay = scroll_page()
        root.addWidget(page, 1)

        self.cards_holder = QWidget()
        self.cards_lay = QVBoxLayout(self.cards_holder)
        self.cards_lay.setContentsMargins(0, 0, 0, 0)
        self.cards_lay.setSpacing(theme.scaled(theme.GAP))
        self.lay.addWidget(self.cards_holder)

        self.lay.addWidget(self._build_arrange())
        self.lay.addWidget(self._build_topology())
        self.lay.addWidget(self._build_profiles())
        self.lay.addStretch(0)

        self.reload()

    # ── perfis ───────────────────────────────────────────────────────────────
    def _build_profiles(self) -> Card:
        card = Card("Perfis", theme.DISK, "guarda quais telas ficam ligadas e em que modo")
        self.profiles_box = QVBoxLayout()
        self.profiles_box.setSpacing(theme.scaled(6))
        card.add_layout(self.profiles_box)
        card.add(divider())

        row = QHBoxLayout()
        row.setSpacing(theme.scaled(8))
        self.profile_name = QLineEdit()
        self.profile_name.setPlaceholderText("nome do perfil, ex: Jogo na TV")
        btn = PillButton("Salvar estado atual", theme.DISK, filled=True)
        btn.clicked.connect(self._save_profile)
        seed = PillButton("Recriar prontos", theme.MUTE)
        seed.clicked.connect(self._seed_profiles)
        row.addWidget(self.profile_name, 1)
        row.addWidget(btn)
        row.addWidget(seed)
        card.add_layout(row)
        return card

    def _build_arrange(self) -> Card:
        card = Card("Arranjo", theme.FPS, "arraste as telas; elas colam nas vizinhas")
        self.canvas = ArrangeCanvas()
        self.canvas.moved.connect(self._arrange_dirty)
        card.add(self.canvas, 1)
        row = QHBoxLayout()
        row.setSpacing(theme.scaled(8))
        self.btn_arrange = PillButton("Aplicar posições", theme.FPS, filled=True)
        self.btn_arrange.clicked.connect(self._apply_arrange)
        self.btn_arrange.setVisible(False)
        reset = PillButton("Descartar", theme.MUTE)
        reset.clicked.connect(self.reload)
        self.btn_reset = reset
        self.btn_reset.setVisible(False)
        row.addWidget(self.btn_arrange)
        row.addWidget(self.btn_reset)
        row.addStretch(1)
        card.add_layout(row)
        return card

    def _arrange_dirty(self) -> None:
        self.btn_arrange.setVisible(True)
        self.btn_reset.setVisible(True)

    def _apply_arrange(self) -> None:
        before = D.snapshot()
        ok, err = ccd.set_positions(self.canvas.positions())
        if not ok:
            self.notify(err, theme.BAD)
            self.reload()
            return
        self.confirm_or_revert("posições aplicadas", lambda: D.apply_profile(before))

    def _build_topology(self) -> Card:
        card = Card("Modos rápidos", theme.CPU, "o mesmo que o Win+P faz")
        row = QHBoxLayout()
        row.setSpacing(theme.scaled(8))
        for text, mode, color in (("Estender", "extend", theme.OK),
                                  ("Clonar", "clone", theme.FPS),
                                  ("Só a principal", "internal", theme.MUTE),
                                  ("Só as externas", "external", theme.MUTE)):
            btn = PillButton(text, color)
            btn.clicked.connect(lambda m=mode, t=text: self._topology(m, t))
            row.addWidget(btn)
        row.addStretch(1)
        card.add_layout(row)

        self.c_ao_abrir = QCheckBox("Aplicar o arranjo padrão quando o DBX Stats abrir")
        self.c_ao_abrir.setChecked(bool(self.cfg.display_apply_on_start))
        self.c_ao_abrir.toggled.connect(self._set_ao_abrir)
        card.add(self.c_ao_abrir)

        self.c_after_game = QCheckBox("Voltar ao perfil padrão quando um jogo fechar")
        self.c_after_game.setChecked(bool(self.cfg.display_restore_after_game))
        self.c_after_game.toggled.connect(self._set_after_game)
        card.add(self.c_after_game)

        self.c_restore = QCheckBox("Aplicar o arranjo padrão ao fechar o DBX Stats")
        self.c_restore.setChecked(bool(self.cfg.display_restore_on_exit))
        self.c_restore.toggled.connect(self._set_restore)
        card.add(self.c_restore)

        self.c_nativa = QCheckBox("Corrigir resolução e taxa para a nativa de cada painel")
        self.c_nativa.setToolTip(
            "O Windows escolhe um modo conservador ao reanexar uma tela: numa TV 4K "
            "vira 60 Hz, e num painel de 144 vira 120. Vale na abertura do app e "
            "quando um monitor entra ou sai — nunca no meio do uso.")
        self.c_nativa.setChecked(bool(self.cfg.display_force_native))
        self.c_nativa.toggled.connect(self._set_nativa)
        card.add(self.c_nativa)

        acoes = QHBoxLayout()
        acoes.setSpacing(theme.scaled(8))
        aplicar = PillButton("Aplicar arranjo padrão agora", theme.FPS, filled=True)
        aplicar.setToolTip("Acende o que deve estar aceso, entrega a primária a quem "
                           "você escolheu, apaga o que deve ficar apagado e devolve "
                           "cada tela ao modo nativo.")
        aplicar.clicked.connect(self._aplicar_padrao)
        acoes.addWidget(aplicar)
        acoes.addStretch(1)
        card.add_layout(acoes)

        self.resumo_padrao = label("", 8.5, color=theme.MUTE)
        self.resumo_padrao.setWordWrap(True)
        card.add(self.resumo_padrao)
        self._descrever_padrao()
        return card

    def _set_ao_abrir(self, on: bool) -> None:
        self.cfg.display_apply_on_start = bool(on)
        self.cfg.save()

    def _set_nativa(self, on: bool) -> None:
        self.cfg.display_force_native = bool(on)
        self.cfg.save()

    def _descrever_padrao(self) -> None:
        """Diz em uma linha o que "arranjo padrao" significa hoje.

        Sem isso a promessa fica invisivel: os dois marcadores vivem cada um no
        cartao da sua tela, e ninguem junta as pecas de cabeca.
        """
        nomes = {d.monitor_id: d.name for d in D.list_displays(with_modes=False)}
        principal = nomes.get(self.cfg.display_primary_default, "")
        apagadas = [nomes.get(m, "?") for m in self.cfg.display_off_by_default
                    if m in nomes]
        partes = []
        partes.append(f"principal: {principal}" if principal
                      else "principal: nenhuma escolhida")
        if apagadas:
            partes.append("apagadas: " + ", ".join(apagadas))
        if self.cfg.display_force_native:
            partes.append("modo nativo")
        self.resumo_padrao.setText("Arranjo padrão — " + "   ·   ".join(partes))

    def _aplicar_padrao(self) -> None:
        aplicar = getattr(self.app, "_enforce_display_defaults", None)
        if aplicar is None:
            return
        try:
            aplicar()
        except Exception as e:                                   # noqa: BLE001
            self.notify(f"não consegui aplicar: {e}", theme.BAD)
            return
        self.notify("Arranjo padrão aplicado.", theme.OK)
        self.reload()

    def _set_restore(self, on: bool) -> None:
        self.cfg.display_restore_on_exit = bool(on)
        self.cfg.save()

    def _set_after_game(self, on: bool) -> None:
        self.cfg.display_restore_after_game = bool(on)
        self.cfg.save()

    def _topology(self, mode: str, label_text: str) -> None:
        before = D.snapshot()
        ok, err = ccd.set_topology_mode(mode)
        if not ok:
            self.notify(f"{label_text}: {err}", theme.BAD)
            self.reload()
            return
        self.confirm_or_revert(f"{label_text} aplicado", lambda: D.apply_profile(before))

    def _seed_profiles(self) -> None:
        seeded = D.suggested_profiles()
        if not seeded:
            self.notify("nenhuma tela encontrada para montar perfis", theme.WARN)
            return
        existing = {p["name"] for p in self.cfg.display_profiles}
        novos = [p for p in seeded if p["name"] not in existing]
        self.cfg.display_profiles = self.cfg.display_profiles + novos
        self.cfg.save()
        self._refresh_profiles()
        self.notify(f"{len(novos)} perfil(is) criado(s)" if novos
                    else "os perfis prontos já existem", theme.OK)

    def _refresh_profiles(self) -> None:
        _clear_layout(self.profiles_box)
        profiles = self.cfg.display_profiles
        if not profiles:
            self.profiles_box.addWidget(
                label("nenhum perfil salvo ainda", 9, color=theme.FAINT))
            return
        for index, profile in enumerate(profiles):
            row = QHBoxLayout()
            row.setSpacing(theme.scaled(8))
            ligadas = [e for e in profile["entries"] if e.get("active")]
            resumo = ", ".join(e.get("name") or e.get("device", "") for e in ligadas)
            espelho = profile.get("topology") == "clone"
            padrao = profile["name"] == self.cfg.display_default_profile
            if espelho:
                resumo = f"espelho · {resumo}"
            if padrao:
                resumo = f"{resumo}  —  é para cá que tudo volta"
            col = QVBoxLayout()
            col.setSpacing(0)
            titulo = QHBoxLayout()
            titulo.setSpacing(theme.scaled(6))
            titulo.addWidget(label(profile["name"], 10, color=theme.TXT))
            if espelho:
                titulo.addWidget(Badge("espelho", theme.FPS))
            if padrao:
                titulo.addWidget(Badge("padrão", theme.OK))
            titulo.addStretch(1)
            col.addLayout(titulo)
            col.addWidget(label(resumo, 8, color=theme.FAINT))
            row.addLayout(col, 1)
            apply_btn = PillButton("Aplicar", theme.OK, filled=True)
            apply_btn.clicked.connect(lambda i=index: self._apply_profile(i))
            padrao_btn = PillButton("Padrão" if not padrao else "Padrão ✓",
                                    theme.OK if padrao else theme.MUTE)
            padrao_btn.clicked.connect(lambda i=index: self._set_default(i))
            del_btn = PillButton("Excluir", theme.BAD)
            del_btn.clicked.connect(lambda i=index: self._delete_profile(i))
            row.addWidget(apply_btn)
            row.addWidget(padrao_btn)
            row.addWidget(del_btn)
            self.profiles_box.addLayout(row)

    def save_mirror_profile(self, anchor: D.Display) -> None:
        profile = D.mirror_profile(anchor, [c.disp for c in self._cards])
        profiles = [p for p in self.cfg.display_profiles if p["name"] != profile["name"]]
        profiles.append(profile)
        self.cfg.display_profiles = profiles
        self.cfg.save()
        self._refresh_profiles()
        modo = next((e["mode"] for e in profile["entries"] if e.get("primary")), None)
        detalhe = f" em {modo[0]}x{modo[1]} @ {modo[2]} Hz" if modo else ""
        self.notify(f"perfil '{profile['name']}' salvo{detalhe}", theme.OK)

    def _save_profile(self) -> None:
        name = self.profile_name.text().strip()
        if not name:
            self.notify("dê um nome ao perfil antes de salvar", theme.WARN)
            return
        entries = D.snapshot()
        profiles = [p for p in self.cfg.display_profiles if p["name"] != name]
        profiles.append({"name": name[:40], "hotkey": "",
                         "topology": "clone" if D.looks_cloned() else "",
                         "entries": entries})
        self.cfg.display_profiles = profiles
        self.cfg.save()
        self.profile_name.clear()
        self._refresh_profiles()
        self.notify(f"perfil '{name}' salvo", theme.OK)

    def _apply_profile(self, index: int) -> None:
        try:
            profile = self.cfg.display_profiles[index]
        except IndexError:
            return
        before = D.snapshot()
        ok, err = D.apply_profile(profile["entries"], profile.get("topology", ""))
        if not ok:
            self.notify(err, theme.BAD)
            self.reload()
            return
        self.confirm_or_revert(f"perfil '{profile['name']}' aplicado",
                               lambda: D.apply_profile(before))

    def _set_default(self, index: int) -> None:
        """Marca (ou desmarca) o perfil que vale como 'meu normal'."""
        try:
            profile = self.cfg.display_profiles[index]
        except IndexError:
            return
        virou = "" if self.cfg.display_default_profile == profile["name"] else profile["name"]
        self.cfg.display_default_profile = virou
        self.cfg.save()
        self._refresh_profiles()
        self.notify(f"'{profile['name']}' é o arranjo padrão — é para cá que as telas "
                    "voltam depois do jogo e ao fechar o app" if virou
                    else "sem perfil padrão; volta para o estado de quando o app abriu",
                    theme.OK if virou else theme.MUTE)

    def _delete_profile(self, index: int) -> None:
        try:
            removed = self.cfg.display_profiles.pop(index)
        except IndexError:
            return
        self.cfg.save()
        self._refresh_profiles()
        self.notify(f"perfil '{removed['name']}' excluído", theme.MUTE)

    # ── ciclo ────────────────────────────────────────────────────────────────
    def reload(self) -> None:
        for card in self._cards:
            card.setParent(None)
            card.deleteLater()
        self._cards.clear()

        found = D.list_displays()
        for disp in found:
            card = _DisplayCard(disp, self)
            self.cards_lay.addWidget(card)
            self._cards.append(card)

        active = [d for d in found if d.active]
        primary = next((d for d in found if d.primary), None)
        pixels = sum(d.mode.width * d.mode.height for d in active if d.mode)
        self.kpi.set("total", str(len(found)), theme.TXT)
        self.kpi.set("on", str(len(active)), theme.OK if active else theme.BAD)
        self.kpi.set("primary", primary.name.split(" ")[0] if primary else "—", theme.RAM)
        self.kpi.set("pixels", f"{pixels / 1_000_000:.1f}M", theme.FPS)
        self.canvas.load(found)
        self.btn_arrange.setVisible(False)
        self.btn_reset.setVisible(False)

        # Primeira abertura ja' vem com perfis utilizaveis. Tela vazia com um
        # botao "salvar" nao ensina nada sobre o que a funcao faz.
        if not self.cfg.display_profiles:
            seeded = D.suggested_profiles()
            if seeded:
                self.cfg.display_profiles = seeded
                self.cfg.save()

        self._refresh_profiles()
        if hasattr(self, "resumo_padrao"):
            self._descrever_padrao()

    def on_activate(self) -> None:
        self.reload()

    def notify(self, text: str, color: str = theme.MUTE) -> None:
        self.status.setText(text)
        self.status.setStyleSheet(f"color: {color}; background: transparent;")
        self.status.setVisible(True)
        QTimer.singleShot(6000, lambda: self.status.setVisible(False))

    def confirm_or_revert(self, description: str, undo) -> bool:
        """Pergunta num popup e desfaz sozinho se ninguem responder.

        Modo invalido em TV costuma dar tela preta, e sem imagem nao ha' como
        clicar em nada. O relogio do popup corre e desfaz por conta propria.
        """
        self.reload()
        seconds = int(self.cfg.display_confirm_seconds or 0)
        if seconds <= 0:
            self.notify(description, theme.OK)
            return True
        kept = ask_confirm(description, seconds, undo, self.window())
        self.reload()
        self.notify(f"{description} — mantido" if kept
                    else "sem confirmação, voltei ao estado anterior",
                    theme.OK if kept else theme.WARN)
        return kept


def _clear_layout(layout) -> None:
    # setParent(None) antes do deleteLater: a exclusao so' acontece na volta do
    # laco de eventos, e ate' la' o widget continuaria desenhado por cima do novo.
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget is not None:
            widget.setParent(None)
            widget.deleteLater()
        elif item.layout():
            _clear_layout(item.layout())
