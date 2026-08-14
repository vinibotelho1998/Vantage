"""Tela do controle: mapa visual, estado ao vivo e ajustes.

O desenho acende o que esta' sendo apertado. E' de proposito: e' assim que se
confere se o controle responde antes de entregar o cursor a ele, sem precisar
adivinhar por que "nao acontece nada".
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QHBoxLayout, QSlider, QVBoxLayout, QWidget

from ... import theme
from ...platform import gamepad as G
from ..components import Card, KpiStrip, MetricList, divider, label
from .base import View, scroll_page

_KPIS = [
    ("conn", "Controle", ""), ("mode", "Modo mouse", ""),
    ("slot", "Conectados", ""), ("speed", "Velocidade", "x"),
]

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

    def set_pad(self, pad, live: bool) -> None:
        self.pad = pad
        self.live = live
        self.update()

    # ── estado ───────────────────────────────────────────────────────────────
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

    # ── pintura ──────────────────────────────────────────────────────────────
    _GEOM = {key: (cx, cy, r, w) for key, cx, cy, r, w in _CONTROLS}

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

        for key, cx, cy, radius, width in _CONTROLS:
            pressed = self._pressed(key)
            center = QPointF(cx, cy) + self._tilt(key)
            p.setBrush(QBrush(on if pressed else surface))
            p.setPen(QPen(on if pressed else idle, 2))
            if width:
                p.drawRoundedRect(QRectF(center.x() - radius * 1.7, center.y() - width / 2,
                                         radius * 3.4, width), 5, 5)
            elif key == "dpad":
                braco = radius * 0.42
                p.drawPath(_cross(center, radius, braco))
            else:
                p.drawEllipse(center, radius, radius)
            if key in ("a", "b", "x", "y"):
                p.setPen(QPen(QColor(theme.BG) if pressed else text, 1))
                p.setFont(QFont(theme.FONT_UI, 10, QFont.Weight.Bold))
                p.drawText(QRectF(center.x() - radius, center.y() - radius,
                                  radius * 2, radius * 2),
                           Qt.AlignmentFlag.AlignCenter, key.upper())
            if key in ("lstick", "rstick"):
                p.setBrush(QBrush(QColor(theme.BG_SUNKEN)))
                p.setPen(QPen(idle, 1))
                p.drawEllipse(center, radius * 0.55, radius * 0.55)

        self._callouts(p, _LABELS_LEFT, left=True, on=on, text=text, faint=faint)
        self._callouts(p, _LABELS_RIGHT, left=False, on=on, text=text, faint=faint)

        p.setFont(QFont(theme.FONT_UI, 8, QFont.Weight.DemiBold))
        for key, name in _LABELS_CENTER:
            cx, cy, radius, _ = self._GEOM[key]
            p.setPen(QPen(on if self._pressed(key) else text, 1))
            p.drawText(QRectF(cx - 40, cy - radius - 20, 80, 14),
                       Qt.AlignmentFlag.AlignCenter, name)
        # Fica abaixo do corpo inteiro. No meio ele batia no direcional.
        p.setPen(QPen(faint, 1))
        p.setFont(QFont(theme.FONT_UI, 8))
        p.drawText(QRectF(158, 322, 400, 16), Qt.AlignmentFlag.AlignCenter,
                   "Back + Start assume ou devolve o mouse")
        p.end()

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

    def _body(self, p: QPainter, color: QColor) -> None:
        """Silhueta de Xbox: corpo largo em cima e dois cabos descendo."""
        path = QPainterPath()
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
        p.setBrush(QBrush(QColor(theme.BG_SUNKEN)))
        p.setPen(QPen(color, 2))
        p.drawPath(path)


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

        ref = Card("Tudo que o controle faz", theme.GPU, "gerado do próprio mapeamento")
        self.rows = MetricList([(str(i), name) for i, (name, _) in enumerate(G.describe())])
        for i, (_, action) in enumerate(G.describe()):
            self.rows.set(str(i), action)
        ref.add(self.rows)
        lay.addWidget(ref, 1)
        lay.addStretch(0)

        pad = getattr(app, "gamepad", None)
        if pad is not None:
            pad.connected_changed.connect(self._refresh)
            pad.active_changed.connect(self._refresh)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._refresh()

    # ── ajustes ──────────────────────────────────────────────────────────────
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

    # ── ciclo ────────────────────────────────────────────────────────────────
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
        quantos = len(pad.slots) if pad is not None else 0
        self.kpi.set("slot", str(quantos) if quantos else "—",
                     theme.OK if quantos > 1 else theme.TXT)
        self.kpi.set("speed", f"{self.cfg.gamepad_speed:.2f}", theme.RAM)
        if not conectado:
            self.status.setText("aguardando um controle conectar")
        elif not ativo:
            self.status.setText("conectado; aperte Back + Start para assumir o mouse")
        else:
            self.status.setText("controlando o mouse")

    def _tick(self) -> None:
        pad = getattr(self.app, "gamepad", None)
        self.diagram.set_pad(getattr(pad, "last", None), pad is not None and pad.active)

    def on_activate(self) -> None:
        self._refresh()
        self._timer.start(50)

    def hideEvent(self, event) -> None:
        self._timer.stop()
        super().hideEvent(event)
