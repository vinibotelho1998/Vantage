"""Tela do controle: mapa visual, estado ao vivo e ajustes.

O desenho acende o que esta' sendo apertado. E' de proposito: e' assim que se
confere se o controle responde antes de entregar o cursor a ele, sem precisar
adivinhar por que "nao acontece nada".
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import (QBrush, QColor, QFont, QLinearGradient, QPainter,
                           QPainterPath, QPen, QRadialGradient)
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QSlider, QVBoxLayout, QWidget

from ... import theme
from ...platform import gamepad as G
from ...platform import pads as P
from ..components import Badge, Card, KpiStrip, PillButton, divider, label
from .base import View, scroll_page

_KPIS = [
    ("conn", "Controle", ""), ("mode", "Modo mouse", ""),
    ("slot", "Conectados", ""), ("speed", "Velocidade", "x"),
]

_PADS_MS = 2000
"""Cadencia da varredura de dispositivos.

Bem mais lenta que a do desenho de proposito: a varredura abre um handle por
dispositivo HID da maquina, o que custa milissegundos, e conectar um controle
nao e' evento que precise de resposta em 50 ms."""

# Espaco de desenho 700 x 360, escalado no paintEvent. As posicoes seguem o
# layout do Xbox: analogico esquerdo em cima a esquerda, direcional embaixo dele,
# botoes ABXY em cima a direita e analogico direito embaixo deles.
_R = 16.0
_CONTROLS = [
    ("lt", 232, 52, 18, 11),
    ("lb", 238, 88, 20, 12),
    ("lstick", 248, 152, 29, 0),
    ("dpad", 306, 232, 25, 0),
    ("back", 320, 156, 11, 0),
    ("start", 380, 156, 11, 0),
    ("y", 452, 124, _R, 0),
    ("x", 424, 152, _R, 0),
    ("b", 480, 152, _R, 0),
    ("a", 452, 180, _R, 0),
    ("rb", 462, 88, 20, 12),
    ("rt", 468, 52, 18, 11),
    ("rstick", 394, 232, 29, 0),
]

# No DualSense os dois analogicos ficam embaixo, lado a lado, e o direcional sobe
# para o lugar que no Xbox e' do analogico esquerdo. Desenhar sempre a silhueta
# do Xbox obrigava o dono de um DualSense a traduzir a posicao de cada botao de
# cabeca, justamente na tela que existe para conferir se o controle responde.
_CONTROLS_SONY = [
    ("lt", 232, 52, 18, 11),
    ("lb", 238, 88, 20, 12),
    ("dpad", 262, 152, 25, 0),
    ("lstick", 306, 232, 29, 0),
    ("back", 322, 150, 9, 0),
    ("start", 394, 150, 9, 0),
    ("y", 454, 124, _R, 0),
    ("x", 426, 152, _R, 0),
    ("b", 482, 152, _R, 0),
    ("a", 454, 180, _R, 0),
    ("rb", 462, 88, 20, 12),
    ("rt", 468, 52, 18, 11),
    ("rstick", 410, 232, 29, 0),
]

_GLIFOS_SONY = {"a": "✕", "b": "○", "x": "□", "y": "△"}
"""As faces da Sony sao formas, nao letras.

O app fala em A/B/X/Y porque e' o vocabulario do XInput, mas quem esta' com um
DualSense na mao ve' simbolos, e "aperte A" nao ajuda a achar nada.
"""

_CORES_SONY = {"a": "#7A8CDB", "b": "#E86A7C", "x": "#D48FD0", "y": "#5BC8A5"}
"""Cor de cada simbolo da Sony, suavizada para o fundo escuro do app."""

# Cada rotulo tem faixa vertical propria. Ancorar o texto na altura do botao,
# como estava antes, faz ABXY e os dois miolos colidirem, porque varios deles
# dividem a mesma linha no desenho.
_LABELS_LEFT = [
    ("lt", 44, "LT", "Página acima"),
    ("lb", 96, "LB", "Alt+Tab, troca de janela"),
    ("lstick", 152, "Analógico esquerdo", "Move o cursor"),
    ("dpad", 232, "Direcional", "Setas do teclado"),
]
_LABELS_RIGHT = [
    ("rt", 44, "RT", "Página abaixo"),
    ("rb", 96, "RB", "Tecla Windows"),
    ("y", 140, "Y", "Esc"),
    ("b", 180, "B", "Clique direito"),
    ("a", 220, "A", "Clique esquerdo"),
    ("x", 260, "X", "Backspace, apaga"),
    ("rstick", 306, "Analógico direito", "Rola a página"),
]
# No DualSense o direcional e o analogico trocam de altura, e o rotulo tem de
# trocar junto: ancorado na altura do Xbox, o tracejado de cada um atravessava o
# corpo inteiro para alcancar a peca do outro lado, cruzando em X sobre o
# desenho.
_LABELS_LEFT_SONY = [
    ("lt", 44, "LT", "Página acima"),
    ("lb", 96, "LB", "Alt+Tab, troca de janela"),
    ("dpad", 152, "Direcional", "Setas do teclado"),
    ("lstick", 232, "Analógico esquerdo", "Move o cursor"),
]

_LABELS_CENTER = [
    ("back", "Back"), ("start", "Start"),
]

_MASKS = {
    "a": G.BTN_A, "b": G.BTN_B, "x": G.BTN_X, "y": G.BTN_Y,
    "lb": G.BTN_LB, "rb": G.BTN_RB, "back": G.BTN_BACK, "start": G.BTN_START,
    "lstick": G.BTN_LTHUMB, "rstick": G.BTN_RTHUMB,
}


def _cross(center: QPointF, raio: float, braco: float) -> QPainterPath:
    """Cruz do direcional. Circulo cheio nao le como direcional nenhum."""
    path = QPainterPath()
    path.addRect(QRectF(center.x() - braco, center.y() - raio, braco * 2, raio * 2))
    path.addRect(QRectF(center.x() - raio, center.y() - braco, raio * 2, braco * 2))
    return path.simplified()


class ControllerDiagram(QWidget):
    """Desenho do controle com destaque do que esta' pressionado."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(theme.scaled(300))
        self.pad = None
        self.live = False
        self.kind = "xbox"
        """"xbox" ou "sony". Decide silhueta, posicao dos analogicos e simbolos."""

    def set_pad(self, pad, live: bool) -> None:
        self.pad = pad
        self.live = live
        self.update()

    def set_kind(self, kind: str) -> None:
        if kind != self.kind:
            self.kind = kind
            self.update()

    @property
    def controles(self) -> list:
        return _CONTROLS_SONY if self.kind == "sony" else _CONTROLS

    def _pressed(self, key: str) -> bool:
        if self.pad is None:
            return False
        mask = _MASKS.get(key)
        if mask is not None:
            return bool(self.pad.wButtons & mask)
        if key == "lt":
            return self.pad.bLeftTrigger > G.TRIGGER_THRESHOLD
        if key == "rt":
            return self.pad.bRightTrigger > G.TRIGGER_THRESHOLD
        if key == "dpad":
            return bool(self.pad.wButtons & (G.BTN_DPAD_UP | G.BTN_DPAD_DOWN
                                             | G.BTN_DPAD_LEFT | G.BTN_DPAD_RIGHT))
        return False

    def _tilt(self, key: str) -> QPointF:
        """Deslocamento do analogico, para ele se mexer junto no desenho."""
        if self.pad is None:
            return QPointF(0, 0)
        if key == "lstick":
            x, y = self.pad.sThumbLX, self.pad.sThumbLY
        elif key == "rstick":
            x, y = self.pad.sThumbRX, self.pad.sThumbRY
        else:
            return QPointF(0, 0)
        return QPointF(x / 32767 * 9, -y / 32767 * 9)

    @property
    def _GEOM(self) -> dict:
        return {key: (cx, cy, r, w) for key, cx, cy, r, w in self.controles}

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        scale = min(self.width() / 700.0, self.height() / 360.0)
        p.translate((self.width() - 700 * scale) / 2, (self.height() - 360 * scale) / 2)
        p.scale(scale, scale)

        idle = QColor(theme.LINE_HI)
        on = QColor(theme.OK)
        text = QColor(theme.MUTE)
        faint = QColor(theme.FAINT)
        surface = QColor(theme.SURFACE)

        self._body(p, idle)

        for key, cx, cy, radius, width in self.controles:
            pressed = self._pressed(key)
            center = QPointF(cx, cy) + self._tilt(key)
            if width:
                self._ombro(p, center, radius, width, pressed, on, idle)
            elif key == "dpad":
                self._direcional(p, center, radius, pressed, on, idle)
            elif key in ("lstick", "rstick"):
                self._analogico(p, QPointF(cx, cy), center, radius, pressed, on, idle)
            else:
                self._botao(p, key, center, radius, pressed, on, idle, text)

        esquerda = _LABELS_LEFT_SONY if self.kind == "sony" else _LABELS_LEFT
        self._callouts(p, esquerda, left=True, on=on, text=text, faint=faint)
        self._callouts(p, _LABELS_RIGHT, left=False, on=on, text=text, faint=faint)

        p.setFont(QFont(theme.FONT_UI, 8, QFont.Weight.DemiBold))
        for key, name in _LABELS_CENTER:
            cx, cy, radius, _ = self._GEOM[key]
            # No DualSense esses botoes tem outro nome impresso. Chamar de
            # "Back" o botao escrito "Create" manda procurar o que nao existe.
            if self.kind == "sony":
                name = {"back": "Create", "start": "Options"}.get(key, name)
            p.setPen(QPen(on if self._pressed(key) else text, 1))
            p.drawText(QRectF(cx - 30, cy - radius - 19, 60, 14),
                       Qt.AlignmentFlag.AlignCenter, name)
        # Fica abaixo do corpo inteiro. No meio ele batia no direcional.
        p.setPen(QPen(faint, 1))
        p.setFont(QFont(theme.FONT_UI, 8))
        combo = ("Create + Options assume ou devolve o mouse" if self.kind == "sony"
                 else "Back + Start assume ou devolve o mouse")
        p.drawText(QRectF(158, 326, 400, 16), Qt.AlignmentFlag.AlignCenter, combo)
        p.end()

    @staticmethod
    def _sombra(p: QPainter, desenhar, deslocamento: float = 2.4) -> None:
        """Repete a peca deslocada e escura, por baixo.

        E' o que da' altura: sem a sombra a peca fica pintada NO corpo, e com ela
        fica EM CIMA do corpo, que e' como o controle e' de verdade.
        """
        p.save()
        p.translate(0, deslocamento)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(QColor(0, 0, 0, 120)))
        desenhar(p)
        p.restore()

    @staticmethod
    def _domo(centro: QPointF, raio: float, base: QColor, topo: QColor) -> QRadialGradient:
        """Gradiente de cupula: a luz bate no alto e a esquerda, como no corpo.

        O foco fora do centro e' o detalhe que faz o circulo parecer redondo em
        vez de chapado: centrado, ele viraria um alvo de tiro.
        """
        grad = QRadialGradient(centro.x() - raio * 0.35, centro.y() - raio * 0.4,
                               raio * 1.6)
        grad.setColorAt(0.0, topo)
        grad.setColorAt(1.0, base)
        return grad

    def _botao(self, p: QPainter, key: str, centro: QPointF, raio: float,
               pressed: bool, on: QColor, idle: QColor, text: QColor) -> None:
        """Botao redondo de face, com brilho proprio quando apertado."""
        if not pressed:
            self._sombra(p, lambda q: q.drawEllipse(centro, raio, raio))

        if pressed:
            # Aceso: um halo em volta antes do botao. A' distancia da poltrona o
            # brilho e' o que se ve'; a troca de cor sozinha se perde.
            halo = QRadialGradient(centro, raio * 2.1)
            halo.setColorAt(0.0, QColor(on.red(), on.green(), on.blue(), 120))
            halo.setColorAt(1.0, QColor(on.red(), on.green(), on.blue(), 0))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(halo))
            p.drawEllipse(centro, raio * 2.1, raio * 2.1)
            base, claro = on, on.lighter(135)
        else:
            base, claro = QColor(theme.SURFACE_2), QColor(theme.LINE_HI)

        p.setBrush(QBrush(self._domo(centro, raio, base, claro)))
        p.setPen(QPen(on if pressed else idle, 1.4))
        # Pressionado afunda um pouco: o mesmo botao, so' que menor.
        r = raio * (0.93 if pressed else 1.0)
        p.drawEllipse(centro, r, r)

        # So' as quatro faces levam simbolo. Back e Start sao circulos pequenos:
        # a palavra inteira nao cabe dentro e saia recortada, virando duas letras
        # soltas coladas no botao. O nome deles ja' vem do rotulo, fora do corpo.
        if key not in ("a", "b", "x", "y"):
            return
        simbolo = (_GLIFOS_SONY.get(key, key.upper()) if self.kind == "sony"
                   else key.upper())
        if self.kind == "sony" and not pressed:
            cor_simbolo = QColor(_CORES_SONY.get(key, theme.MUTE))
        else:
            cor_simbolo = QColor(theme.BG) if pressed else text
        p.setPen(QPen(cor_simbolo, 1))
        p.setFont(QFont(theme.FONT_UI, 11 if self.kind == "sony" else 10,
                        QFont.Weight.Bold))
        p.drawText(QRectF(centro.x() - raio, centro.y() - raio, raio * 2, raio * 2),
                   Qt.AlignmentFlag.AlignCenter, simbolo)

    def _analogico(self, p: QPainter, fixo: QPointF, centro: QPointF, raio: float,
                   pressed: bool, on: QColor, idle: QColor) -> None:
        """Analogico: poco fixo, e por cima o disco que se move com a mao.

        O poco NAO acompanha a inclinacao de proposito: ele e' o buraco no corpo
        do controle, e ver o disco correr dentro dele e' o que mostra o quanto o
        analogico esta' deflexionado.
        """
        poco = QRadialGradient(fixo, raio * 1.15)
        poco.setColorAt(0.0, QColor(0, 0, 0, 190))
        poco.setColorAt(1.0, QColor(theme.BG_SUNKEN))
        p.setPen(QPen(QColor(theme.LINE), 1))
        p.setBrush(QBrush(poco))
        p.drawEllipse(fixo, raio * 1.12, raio * 1.12)

        self._sombra(p, lambda q: q.drawEllipse(centro, raio, raio), 3.0)
        base = on if pressed else QColor(theme.SURFACE_2)
        claro = on.lighter(130) if pressed else QColor(theme.LINE_HI)
        p.setBrush(QBrush(self._domo(centro, raio, base, claro)))
        p.setPen(QPen(on if pressed else idle, 1.6))
        p.drawEllipse(centro, raio, raio)

        # Miolo emborrachado: mais escuro e afundado, como no controle real.
        miolo = QRadialGradient(centro.x() - raio * 0.2, centro.y() - raio * 0.25,
                                raio * 0.9)
        miolo.setColorAt(0.0, QColor(theme.SURFACE))
        miolo.setColorAt(1.0, QColor(theme.BG_SUNKEN))
        p.setBrush(QBrush(miolo))
        p.setPen(QPen(QColor(theme.LINE), 1))
        p.drawEllipse(centro, raio * 0.58, raio * 0.58)

    def _direcional(self, p: QPainter, centro: QPointF, raio: float,
                    pressed: bool, on: QColor, idle: QColor) -> None:
        braco = raio * 0.42
        cruz = _cross(centro, raio, braco)
        if not pressed:
            self._sombra(p, lambda q: q.drawPath(cruz))
        base = on if pressed else QColor(theme.SURFACE_2)
        claro = on.lighter(130) if pressed else QColor(theme.LINE_HI)
        grad = QLinearGradient(centro.x(), centro.y() - raio,
                               centro.x(), centro.y() + raio)
        grad.setColorAt(0.0, claro)
        grad.setColorAt(1.0, base)
        p.setBrush(QBrush(grad))
        p.setPen(QPen(on if pressed else idle, 1.4))
        p.drawPath(cruz)

    def _ombro(self, p: QPainter, centro: QPointF, raio: float, altura: float,
               pressed: bool, on: QColor, idle: QColor) -> None:
        """Gatilho e botao de ombro: barra deitada, iluminada por cima."""
        rect = QRectF(centro.x() - raio * 1.7, centro.y() - altura / 2,
                      raio * 3.4, altura)
        if not pressed:
            self._sombra(p, lambda q: q.drawRoundedRect(rect, 5, 5), 2.0)
        base = on if pressed else QColor(theme.SURFACE_2)
        claro = on.lighter(130) if pressed else QColor(theme.LINE_HI)
        grad = QLinearGradient(0, rect.top(), 0, rect.bottom())
        grad.setColorAt(0.0, claro)
        grad.setColorAt(1.0, base)
        p.setBrush(QBrush(grad))
        p.setPen(QPen(on if pressed else idle, 1.4))
        p.drawRoundedRect(rect, 5, 5)

    def _callouts(self, p: QPainter, itens, left: bool, on, text, faint) -> None:
        edge = 16.0 if left else 684.0
        largura = 170.0
        for key, y, name, acao in itens:
            cx, cy, radius, width = self._GEOM[key]
            pressed = self._pressed(key)
            tip_x = cx - (radius * (1.7 if width else 1.0)) if left else \
                cx + (radius * (1.7 if width else 1.0))
            anchor = edge + largura if left else edge - largura

            p.setPen(QPen(faint, 1, Qt.PenStyle.DotLine))
            p.drawLine(QPointF(anchor, y), QPointF(tip_x, cy))
            p.setBrush(QBrush(on if pressed else faint))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(QPointF(anchor, y), 2.5, 2.5)

            box = QRectF(edge if left else edge - largura, y - 16, largura, 15)
            align = (Qt.AlignmentFlag.AlignLeft if left else Qt.AlignmentFlag.AlignRight)
            p.setPen(QPen(on if pressed else text, 1))
            p.setFont(QFont(theme.FONT_UI, 8.5, QFont.Weight.DemiBold))
            p.drawText(box, align | Qt.AlignmentFlag.AlignVCenter, name)
            p.setPen(QPen(faint, 1))
            p.setFont(QFont(theme.FONT_UI, 7.5))
            p.drawText(QRectF(box.x(), y - 1, largura, 14),
                       align | Qt.AlignmentFlag.AlignVCenter, acao)

    def _silhueta(self) -> QPainterPath:
        """Contorno do corpo, na proporcao do tipo de controle desenhado."""
        path = QPainterPath()
        if self.kind == "sony":
            # DualSense: ombros mais quadrados e cabos mais longos e retos.
            path.moveTo(286, 100)
            path.cubicTo(330, 90, 386, 90, 430, 100)
            path.cubicTo(482, 110, 514, 126, 526, 166)
            path.cubicTo(546, 230, 524, 300, 478, 306)
            path.cubicTo(436, 310, 418, 278, 404, 246)
            path.cubicTo(392, 220, 378, 210, 358, 210)
            path.cubicTo(338, 210, 324, 220, 312, 246)
            path.cubicTo(298, 278, 280, 310, 238, 306)
            path.cubicTo(192, 300, 170, 230, 190, 166)
            path.cubicTo(202, 126, 234, 110, 286, 100)
        else:
            path.moveTo(280, 104)
            path.cubicTo(330, 92, 390, 92, 440, 104)
            path.cubicTo(486, 114, 516, 128, 528, 168)
            path.cubicTo(546, 226, 528, 292, 486, 300)
            path.cubicTo(446, 306, 424, 276, 408, 244)
            path.cubicTo(396, 220, 380, 210, 358, 210)
            path.cubicTo(336, 210, 320, 220, 308, 244)
            path.cubicTo(292, 276, 270, 306, 230, 300)
            path.cubicTo(188, 292, 170, 226, 188, 168)
            path.cubicTo(200, 128, 230, 114, 280, 104)
        return path

    def _body(self, p: QPainter, color: QColor) -> None:
        """Corpo com volume: sombra embaixo, gradiente de cima para baixo e um
        brilho no topo.

        O volume vem de tres camadas empilhadas, e nao de uma imagem pronta.
        Desenhar em vetor mantem o projeto em MIT (arte de terceiros viria com
        licenca e atribuicao junto) e mantem a nitidez em qualquer tamanho, que
        num painel que escala com a janela e' o que mais aparece.
        """
        path = self._silhueta()

        # 1. Sombra: a mesma silhueta deslocada para baixo, sem contorno. E' o que
        # descola o controle do fundo; sem ela o gradiente sozinho le' como
        # mancha, nao como objeto.
        p.save()
        p.translate(0, 7)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(QColor(0, 0, 0, 110)))
        p.drawPath(path)
        p.restore()

        # 2. Corpo: claro no topo e escuro embaixo, como luz vinda de cima.
        corpo = QLinearGradient(0, 96, 0, 306)
        corpo.setColorAt(0.0, QColor(theme.SURFACE_2))
        corpo.setColorAt(0.45, QColor(theme.SURFACE))
        corpo.setColorAt(1.0, QColor(theme.BG_SUNKEN))
        p.setBrush(QBrush(corpo))
        p.setPen(QPen(color, 1.6))
        p.drawPath(path)

        # 3. Brilho especular preso a' metade de cima, recortado pelo corpo.
        p.save()
        p.setClipPath(path)
        brilho = QLinearGradient(0, 96, 0, 200)
        brilho.setColorAt(0.0, QColor(255, 255, 255, 26))
        brilho.setColorAt(1.0, QColor(255, 255, 255, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(brilho))
        p.drawPath(path)
        p.restore()


class PadList(QWidget):
    """Um cartao por controle conectado, legivel pelo app ou nao.

    Existe porque a ausencia era ambigua: um DualSense pareado por Bluetooth
    simplesmente nao aparecia em lugar nenhum, e nao ha' como distinguir "o
    Windows nao pareou" de "o app nao le esse tipo" olhando para uma tela vazia.
    Listar o controle e dizer o porque' resolve os dois casos de uma vez.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._col = QVBoxLayout(self)
        self._col.setContentsMargins(0, 0, 0, 0)
        self._col.setSpacing(theme.scaled(6))
        self._assinatura: tuple | None = None
        self.pads: list[P.Pad] = []
        self._vazio = label("nenhum controle conectado", 8.5, color=theme.FAINT)
        self._col.addWidget(self._vazio)

    def refresh(self) -> list[P.Pad]:
        """Redesenha so' quando a lista muda de verdade.

        A varredura roda a cada dois segundos e quase sempre devolve o mesmo
        conjunto. Reconstruir os widgets a cada volta faria a lista piscar e
        roubaria o foco de quem estivesse navegando de controle.
        """
        try:
            achados = P.list_pads()
        except OSError:
            achados = []
        assinatura = tuple((p.path, p.name, p.xinput, p.slot) for p in achados)
        if assinatura == self._assinatura:
            return self.pads
        self._assinatura = assinatura
        self.pads = achados
        self._rebuild()
        return achados

    def _rebuild(self) -> None:
        while self._col.count():
            item = self._col.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        if not self.pads:
            self._vazio = label("nenhum controle conectado", 8.5, color=theme.FAINT)
            self._col.addWidget(self._vazio)
            return

        for i, pad in enumerate(self.pads):
            if i:
                self._col.addWidget(divider())
            self._col.addWidget(self._linha(pad))

    def _linha(self, pad: P.Pad) -> QWidget:
        caixa = QWidget()
        col = QVBoxLayout(caixa)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(theme.scaled(3))

        topo = QHBoxLayout()
        topo.setSpacing(theme.scaled(6))
        cor = theme.OK if pad.readable else theme.WARN
        topo.addWidget(label(pad.name, 9, QFont.Weight.DemiBold, cor))
        topo.addStretch(1)
        if pad.bus != "—":
            topo.addWidget(Badge(pad.bus, theme.MUTE))
        if pad.how:
            topo.addWidget(Badge(pad.how, theme.CPU))
        if pad.slot is not None:
            topo.addWidget(Badge(f"slot {pad.slot}", theme.CPU))
        col.addLayout(topo)

        rodape = QHBoxLayout()
        rodape.setSpacing(theme.scaled(6))
        if pad.vid:
            rodape.addWidget(label(pad.ids, 7.5, color=theme.FAINT))
        rodape.addStretch(1)
        # "Le'" e "fala XInput" deixaram de ser a mesma coisa quando o app passou
        # a ler os controles da Sony por HID. Quem manda no texto e' a leitura.
        if pad.readable and not pad.xinput:
            texto, cor_txt = "o app lê este controle (HID, sem vibração)", theme.FAINT
        elif pad.readable:
            texto, cor_txt = "o app lê este controle", theme.FAINT
        else:
            texto, cor_txt = "o app não lê: não expõe XInput", theme.WARN
        rodape.addWidget(label(texto, 7.5, color=cor_txt))
        col.addLayout(rodape)
        return caixa


class GamepadView(View):
    key = "gamepad"
    title = "Controle"
    glyph = "⯃"
    subtitle = "usar o PC do sofá"

    def __init__(self, app) -> None:
        super().__init__(app)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(theme.scaled(theme.GAP))

        self.kpi = KpiStrip(_KPIS, columns=4)
        root.addWidget(self.kpi)

        page, lay = scroll_page()
        root.addWidget(page, 1)

        conectados = Card("Controles conectados", theme.FPS,
                          "tudo que o Windows enxerga, não só o que o app lê")
        self.lista = PadList()
        conectados.add(self.lista)
        self.aviso = label("", 8, color=theme.WARN)
        self.aviso.setWordWrap(True)
        self.aviso.hide()
        conectados.add(self.aviso)
        self.preso = label("", 8.5, color=theme.BAD)
        self.preso.setWordWrap(True)
        self.preso.hide()
        conectados.add(self.preso)
        lay.addWidget(conectados)

        card = Card("Mapa do controle", theme.RAM,
                    "os botões acendem quando você aperta")
        self.diagram = ControllerDiagram()
        card.add(self.diagram, 1)
        card.add(divider())
        row = QHBoxLayout()
        row.setSpacing(theme.scaled(8))
        # Sem botao de ligar de proposito: a escuta fica sempre de pe' e quem
        # entrega ou tira o mouse e' o proprio controle, com Back + Start. No sofa
        # nao da' para depender de clicar em nada na tela.
        self.status = label("", 8.5, color=theme.FAINT)
        row.addWidget(self.status, 1)
        card.add_layout(row)
        lay.addWidget(card, 3)

        tune = Card("Ajustes", theme.CPU)
        self.speed = self._slider(tune, "Velocidade do cursor", 20, 400,
                                  int(self.cfg.gamepad_speed * 100), self._speed)
        self.scroll = self._slider(tune, "Velocidade da rolagem", 20, 400,
                                   int(self.cfg.gamepad_scroll_speed * 100), self._scroll)
        self.dead = self._slider(tune, "Zona morta", 0, 20000,
                                 self.cfg.gamepad_deadzone, self._dead)
        lay.addWidget(tune, 1)

        ref = Card("O que cada botão faz", theme.GPU,
                   "escolha a ação; vale na hora, sem reiniciar")
        ref.add(self._mapa())
        lay.addWidget(ref, 1)
        lay.addStretch(0)

        pad = getattr(app, "gamepad", None)
        if pad is not None:
            pad.connected_changed.connect(self._refresh)
            pad.active_changed.connect(self._refresh)

        self._total = 0
        self._legiveis = 0

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._pads_timer = QTimer(self)
        self._pads_timer.timeout.connect(self._scan)
        self._scan()
        self._refresh()

    def _mapa(self) -> QWidget:
        """Uma linha por botao, com a acao num seletor.

        Os analogicos ficam como texto: eles nao sao botao, e trocar a funcao
        deles daria outro app, nao outro mapeamento.
        """
        caixa = QWidget()
        col = QVBoxLayout(caixa)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(theme.scaled(4))

        for nome, acao in (("Analógico esquerdo", "Move o cursor"),
                           ("Analógico direito", "Rola a página"),
                           ("Back + Start", "Assume ou devolve o mouse"),
                           ("LT+RT+L3+R3, duas vezes",
                            "Devolve as telas ao perfil padrão")):
            linha = QHBoxLayout()
            linha.addWidget(label(nome, 8.5, color=theme.MUTE))
            linha.addStretch(1)
            linha.addWidget(label(acao, 8.5, color=theme.FAINT))
            col.addLayout(linha)

        col.addWidget(divider())
        atuais = G.bindings_from(self.cfg)
        opcoes = sorted(G.ACTIONS.items(), key=lambda kv: (kv[0] != "", kv[1][0]))
        self.combos: dict[str, QComboBox] = {}
        for nome in G.BUTTON_ORDER:
            linha = QHBoxLayout()
            linha.addWidget(label(nome, 8.5))
            linha.addStretch(1)
            combo = QComboBox()
            for chave, (rotulo, _) in opcoes:
                combo.addItem(rotulo, chave)
            combo.setCurrentIndex(max(0, combo.findData(atuais.get(nome, ""))))
            combo.currentIndexChanged.connect(
                lambda _i, b=nome, w=combo: self._bind(b, w.currentData()))
            combo.setMinimumWidth(theme.scaled(150))
            self.combos[nome] = combo
            linha.addWidget(combo)
            col.addLayout(linha)

        restaurar = PillButton("Voltar ao padrão", theme.MUTE)
        restaurar.clicked.connect(self._reset_bindings)
        col.addWidget(restaurar)
        return caixa

    def _bind(self, botao: str, acao: str) -> None:
        self.cfg.gamepad_bindings[botao] = acao
        self.cfg.save()
        self._reload_pad()

    def _reset_bindings(self) -> None:
        self.cfg.gamepad_bindings = {}
        self.cfg.save()
        for nome, combo in self.combos.items():
            combo.blockSignals(True)
            combo.setCurrentIndex(max(0, combo.findData(G.DEFAULT_BINDINGS.get(nome, ""))))
            combo.blockSignals(False)
        self._reload_pad()

    def _reload_pad(self) -> None:
        pad = getattr(self.app, "gamepad", None)
        if pad is not None:
            pad.reload_bindings()

    def _slider(self, card: Card, caption: str, lo: int, hi: int, value: int, cb) -> QSlider:
        s = QSlider(Qt.Orientation.Horizontal)
        s.setRange(lo, hi)
        s.setValue(value)
        lbl = label("", 8.5, color=theme.MUTE)
        lbl.setMinimumWidth(theme.scaled(56))
        s.valueChanged.connect(lambda v: (cb(v), lbl.setText(self._fmt(caption, v))))
        lbl.setText(self._fmt(caption, value))
        row = QHBoxLayout()
        row.setSpacing(theme.scaled(8))
        row.addWidget(label(caption, 8.5, color=theme.MUTE))
        row.addWidget(s, 1)
        row.addWidget(lbl)
        card.add_layout(row)
        return s

    @staticmethod
    def _fmt(caption: str, value: int) -> str:
        return f"{value}" if "morta" in caption else f"{value / 100:.2f}x"

    def _speed(self, v: int) -> None:
        self.cfg.gamepad_speed = round(v / 100, 2)

    def _scroll(self, v: int) -> None:
        self.cfg.gamepad_scroll_speed = round(v / 100, 2)

    def _dead(self, v: int) -> None:
        self.cfg.gamepad_deadzone = int(v)

    def _refresh(self, _=None) -> None:
        pad = getattr(self.app, "gamepad", None)
        if not G.available():
            self.status.setText("XInput não disponível nesta máquina")
            self.kpi.set("conn", "—", theme.FAINT)
            return
        conectado = pad is not None and pad.connected
        ativo = pad is not None and pad.active
        self.kpi.set("conn", "sim" if conectado else "não",
                     theme.OK if conectado else theme.FAINT)
        self.kpi.set("mode", "ligado" if ativo else "desligado",
                     theme.OK if ativo else theme.FAINT)
        # Conta a varredura HID, nao os slots XInput: o KPI antigo dizia "0" com
        # um controle na mao, porque contava so' o que o app consegue ler.
        mudos = self._total - self._legiveis
        self.kpi.set("slot", str(self._total) if self._total else "—",
                     theme.WARN if mudos else (theme.OK if self._total else theme.TXT),
                     sub=f"{mudos} sem suporte" if mudos else "")
        self.kpi.set("speed", f"{self.cfg.gamepad_speed:.2f}", theme.RAM)
        if not conectado and self._total and not self._legiveis:
            self.status.setText("há controle conectado, mas nenhum fala XInput")
        elif not conectado:
            self.status.setText("aguardando um controle conectar")
        elif not ativo:
            self.status.setText("conectado; aperte Back + Start para assumir o mouse")
        else:
            self.status.setText("controlando o mouse")

    def _scan(self) -> None:
        """Reconta os controles e explica os que ficaram de fora."""
        lista = self.lista.refresh()
        total, legiveis = len(lista), sum(1 for p in lista if p.readable)
        if (total, legiveis) == (self._total, self._legiveis):
            return
        self._total, self._legiveis = total, legiveis

        # O desenho vira o controle que esta' na mao. Com um DualSense conectado,
        # a silhueta do Xbox obrigava a traduzir cada botao de cabeca.
        sony = any(p.readable and p.vid == P.SONY for p in lista)
        self.diagram.set_kind("sony" if sony else "xbox")

        mudos = [p for p in lista if not p.readable]
        if mudos:
            nomes = ", ".join(p.name for p in mudos)
            self.aviso.setText(
                f"{nomes}: o Windows reconhece, mas o controle só responde aqui "
                "através do XInput. Um tradutor como DS4Windows ou o Steam "
                "(Big Picture, com suporte a PlayStation ligado) resolve: ele "
                "cria um controle XInput virtual que o app passa a ler.")
            self.aviso.show()
        else:
            self.aviso.hide()
        self._refresh()

    def _tick(self) -> None:
        pad = getattr(self.app, "gamepad", None)
        self.diagram.set_pad(getattr(pad, "last", None), pad is not None and pad.active)
        self._avisar_presos(pad)

    def _avisar_presos(self, pad) -> None:
        """Denuncia botao travado, que e' o que move o foco sozinho.

        O sintoma (o foco andando pelo Windows como se alguem batesse nas setas)
        nao aponta para o culpado: o mapeamento manda o direcional para as
        setas do teclado, entao um direcional preso em qualquer controle
        conectado produz exatamente isso, em qualquer aplicativo. Sem este aviso
        so' da' para descobrir desconectando um controle de cada vez.
        """
        presos = pad.stuck() if pad is not None else []
        if not presos:
            self.preso.hide()
            return
        nomes = ", ".join(f"{nome} (há {int(seg)} s)" for nome, seg in presos[:3])
        self.preso.setText(
            f"⚠  {nomes}, o controle está reportando esse botão apertado sem "
            "parar. Com o modo mouse ligado é isso que faz o foco andar sozinho "
            "pelo Windows. Desconecte o controle ou solte o botão.")
        self.preso.show()

    def on_activate(self) -> None:
        self._scan()
        self._refresh()
        self._timer.start(50)
        self._pads_timer.start(_PADS_MS)

    def showEvent(self, event) -> None:
        # O par do hideEvent abaixo. Esconder a janela na bandeja, ou minimizar,
        # esconde esta tela junto e para os dois relogios; sem religar aqui, a
        # volta deixava o desenho do controle congelado ate' trocar de aba, ja'
        # que clicar na aba que continua aberta nao chama on_activate.
        super().showEvent(event)
        self._timer.start(50)
        self._pads_timer.start(_PADS_MS)

    def hideEvent(self, event) -> None:
        self._timer.stop()
        self._pads_timer.stop()
        super().hideEvent(event)
