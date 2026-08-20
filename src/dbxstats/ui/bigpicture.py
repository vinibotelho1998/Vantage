"""Big Picture: escolher e abrir um jogo do sofa, so' com o controle.

Janela propria, e nao a principal em tela cheia. A janela principal constroi as
onze telas no __init__, e cada widget delas ja' chamou theme.scaled() na hora de
nascer — a escala e' global e escrita uma vez so'. Crescer a interface para uma
TV a tres metros exigiria reconstruir tudo. O overlay ja' resolveu esse mesmo
problema do mesmo jeito: janela separada, com escala propria calculada da tela
onde ela vai aparecer.

Nada de sensor ao vivo aqui. Com a janela principal escondida o app cai para o
ritmo de fundo (3 s por leitura), e mostrar fps ou temperatura na grade puxaria
o coletor de volta ao ritmo cheio para um numero que ninguem le' escolhendo
jogo.
"""
from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QApplication, QWidget

from .. import log, theme
from ..platform import gamepad as G

_log = log.get("bigpicture")

REPEAT_FIRST_MS = 350
"""Espera antes de o foco comecar a repetir com o direcional segurado."""
REPEAT_NEXT_MS = 130
COLUNAS_MAX = 4
"""Mais que isso vira card pequeno demais para tres metros de distancia."""

_CORES = (theme.FPS, theme.GPU, theme.CPU, theme.RAM, theme.NET, theme.DISK)


class BigPicture(QWidget):
    """Grade de jogos em tela cheia, navegada pelo controle."""

    fechou = Signal()
    escolheu = Signal(dict)

    def __init__(self, controller) -> None:
        super().__init__()
        self._ctl = controller
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint
                            | Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setWindowTitle("DBX Stats — Big Picture")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._itens: list[dict] = []
        self._foco = 0
        self._escala = 1.0
        self._segurando = ""
        self._proxima_repeticao = 0.0
        self._pressionados: set[int] = set()
        self._aviso = ""
        self._abrindo = ""
        self._sem_controle = False

    # ── ciclo ────────────────────────────────────────────────────────────────
    def abrir(self, screen=None) -> None:
        self._itens = list(self._ctl.settings.launch_items)
        self._foco = min(self._foco, max(0, len(self._itens) - 1))
        self._abrindo = ""
        alvo = screen or QApplication.primaryScreen()
        geo = alvo.geometry()
        self._escala = _escala_para(alvo)
        self.setGeometry(geo)
        self.showFullScreen()
        self.raise_()
        self.activateWindow()
        self.setFocus()
        self.update()

    def fechar(self) -> None:
        self._segurando = ""
        self.hide()
        self.fechou.emit()

    # ── entrada ──────────────────────────────────────────────────────────────
    def tratar_pad(self, pad) -> None:
        """Recebe o estado cru do controle, ja' fundido entre os conectados."""
        self._sem_controle = False
        direcao = G.nav_direction(pad)
        agora = time.monotonic()
        if direcao != self._segurando:
            self._segurando = direcao
            self._proxima_repeticao = agora + REPEAT_FIRST_MS / 1000.0
            if direcao:
                self._mover(direcao)
        elif direcao and agora >= self._proxima_repeticao:
            self._proxima_repeticao = agora + REPEAT_NEXT_MS / 1000.0
            self._mover(direcao)

        b = pad.wButtons
        for mask, acao in ((G.BTN_A, self._confirmar), (G.BTN_START, self._confirmar),
                           (G.BTN_B, self.fechar), (G.BTN_RB, lambda: self._pagina(1)),
                           (G.BTN_LB, lambda: self._pagina(-1))):
            apertado = bool(b & mask)
            if apertado and mask not in self._pressionados:
                self._pressionados.add(mask)
                acao()
            elif not apertado:
                self._pressionados.discard(mask)

    def sem_controle(self) -> None:
        """Aviso quando o controle some — pilha acaba no meio, e acontece."""
        if not self._sem_controle:
            self._sem_controle = True
            self.update()

    def keyPressEvent(self, event) -> None:
        """Teclado como reserva: com o controle sem pilha, ainda da' para sair."""
        tecla = event.key()
        mapa = {Qt.Key.Key_Left: "left", Qt.Key.Key_Right: "right",
                Qt.Key.Key_Up: "up", Qt.Key.Key_Down: "down"}
        if tecla in mapa:
            self._mover(mapa[tecla])
        elif tecla in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self._confirmar()
        elif tecla in (Qt.Key.Key_Escape, Qt.Key.Key_Backspace):
            self.fechar()
        else:
            super().keyPressEvent(event)

    # ── navegacao ────────────────────────────────────────────────────────────
    def _colunas(self) -> int:
        return max(1, min(COLUNAS_MAX, len(self._itens) or 1))

    def _mover(self, direcao: str) -> None:
        if not self._itens:
            return
        colunas = self._colunas()
        antes = self._foco
        if direcao == "left":
            self._foco -= 1
        elif direcao == "right":
            self._foco += 1
        elif direcao == "up":
            self._foco -= colunas
        elif direcao == "down":
            self._foco += colunas
        # Sem dar a volta: o foco saltando da ultima para a primeira desorienta
        # a tres metros, onde nao da' para acompanhar o pulo com o olho.
        self._foco = max(0, min(len(self._itens) - 1, self._foco))
        if self._foco != antes:
            self.update()

    def _pagina(self, passo: int) -> None:
        self._mover("down" if passo > 0 else "up")

    def _confirmar(self) -> None:
        if not self._itens or self._abrindo:
            return
        item = self._itens[self._foco]
        self._abrindo = item.get("name") or Path(item.get("path", "")).stem
        self.update()
        self.escolheu.emit(item)

    # ── desenho ──────────────────────────────────────────────────────────────
    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.fillRect(self.rect(), QColor(theme.BG))
        e = self._escala

        p.setFont(_fonte(22 * e, QFont.Weight.Bold))
        p.setPen(QColor(theme.TXT))
        p.drawText(int(60 * e), int(70 * e), "JOGOS")
        p.setFont(_fonte(11 * e))
        p.setPen(QColor(theme.MUTE))
        rodape = "A abre   ·   B sai   ·   direcional escolhe"
        if self._sem_controle:
            rodape = "Controle desconectado — use as setas e Enter"
        p.drawText(int(60 * e), int(100 * e), rodape)

        if self._abrindo:
            p.setFont(_fonte(26 * e, QFont.Weight.Bold))
            p.setPen(QColor(theme.OK))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                       f"abrindo {self._abrindo}…")
            return

        if not self._itens:
            p.setFont(_fonte(15 * e))
            p.setPen(QColor(theme.MUTE))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                       "Nenhum jogo ainda.\nAdicione pela aba Jogos, no computador.")
            return

        for i, item in enumerate(self._itens):
            self._card(p, i, item, i == self._foco)

    def _grade(self) -> tuple[int, int, int, int, int]:
        e = self._escala
        colunas = self._colunas()
        margem = int(self.width() * 0.045)      # muita TV ainda corta as bordas
        topo = int(130 * e)
        vao = int(24 * e)
        largura = max(1, (self.width() - margem * 2 - vao * (colunas - 1)) // colunas)
        altura = int(largura * 0.62)
        return colunas, margem, topo, largura, altura

    def _card(self, p: QPainter, indice: int, item: dict, focado: bool) -> None:
        colunas, margem, topo, largura, altura = self._grade()
        e = self._escala
        vao = int(24 * e)
        linha, coluna = divmod(indice, colunas)
        x = margem + coluna * (largura + vao)
        y = topo + linha * (altura + vao)
        rect = QRect(x, y, largura, altura)
        if focado:
            # Cresce e brilha. A tres metros o que le' e' tamanho e brilho; uma
            # borda de um pixel, que funciona no monitor, simplesmente some.
            cresce = int(min(largura, altura) * 0.03)
            rect = rect.adjusted(-cresce, -cresce, cresce, cresce)

        cor = QColor(_CORES[indice % len(_CORES)])
        if not focado:
            cor.setAlpha(140)
        caminho = QPainterPath()
        caminho.addRoundedRect(rect, 14 * e, 14 * e)
        p.fillPath(caminho, cor)
        if focado:
            p.setPen(QPen(QColor(theme.TXT), max(3.0, 4 * e)))
            p.drawPath(caminho)

        nome = item.get("name") or Path(item.get("path", "")).stem
        p.setFont(_fonte(max(15.0, 28 * e), QFont.Weight.Bold))
        p.setPen(QColor("#06121c") if focado else QColor(theme.TXT))
        alvo = rect.adjusted(int(20 * e), int(16 * e), int(-20 * e), int(-20 * e))
        p.drawText(alvo, int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
                             | Qt.TextFlag.TextWordWrap), nome)

        p.setFont(_fonte(max(11.0, 14 * e)))
        p.setPen(QColor("#06121c") if focado else QColor(theme.MUTE))
        p.drawText(alvo, int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom),
                   self._rodape_do_card(item))

    def _rodape_do_card(self, item: dict) -> str:
        """Fatos que ajudam a escolher, sem inventar nenhum."""
        partes = []
        caminho = item.get("path", "")
        if caminho and not Path(caminho).exists():
            return "arquivo não encontrado"
        resumo = ultima_sessao(getattr(self._ctl, "session_history", []),
                               item.get("name") or Path(caminho).stem)
        if resumo:
            partes.append(f"{resumo['fps_avg']:.0f} fps na última vez")
        if item.get("target", "").startswith("primary:"):
            partes.append("abre na tela escolhida")
        return "   ·   ".join(partes)


def ultima_sessao(historico, nome: str) -> dict | None:
    """A ultima partida gravada daquele jogo, se houver alguma.

    Sem sessao, devolve None em vez de zero: zero se le' como "rodou a zero fps".
    """
    if not nome:
        return None
    alvo = nome.strip().lower()
    for registro in reversed(list(historico or [])):
        if str(registro.get("game", "")).strip().lower() == alvo:
            return registro
    return None


def tempo_medido(historico, nome: str) -> float:
    """Segundos somados das partidas gravadas daquele jogo.

    "Medido", e nao "jogado": so' entra partida com gravacao ligada e longa o
    bastante para virar registro. Chamar de tempo jogado seria mentir.
    """
    alvo = (nome or "").strip().lower()
    return sum(float(r.get("duracao_s") or 0)
               for r in (historico or [])
               if str(r.get("game", "")).strip().lower() == alvo)


def _escala_para(screen) -> float:
    """Escala propria, do tamanho da tela onde a grade vai aparecer.

    Nao usa theme.scaled(): a escala global e' a do monitor da mesa, e quem
    deixou a interface em 90% por la' teria um Big Picture minusculo na TV.
    """
    try:
        largura = screen.geometry().width()
        dpi = screen.logicalDotsPerInch() or 96.0
    except Exception:                                    # noqa: BLE001
        return 1.0
    escala = (96.0 / dpi) * (largura / 1920.0)
    return max(0.9, min(2.2, escala))


def _fonte(pt: float, peso: int = QFont.Weight.Normal) -> QFont:
    f = QFont(theme.FONT_UI)
    f.setPointSizeF(max(9.0, pt))
    f.setWeight(peso)
    return f


def centro(rect) -> QPoint:
    return QPoint(rect.left() + rect.width() // 2, rect.top() + rect.height() // 2)
