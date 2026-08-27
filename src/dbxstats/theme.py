"""Design tokens do DBX Stats: paleta, tipografia, espacamento e escalas de cor.

Fonte unica de verdade do visual. Nenhum modulo de UI deve declarar cor propria.
"""
from __future__ import annotations

from dataclasses import dataclass

BG = "#080A0F"          # fundo da janela
BG_SUNKEN = "#05070B"   # fundo de graficos / areas rebaixadas
SURFACE = "#0F141C"     # card padrao
SURFACE_2 = "#141B26"   # card elevado / hover
SURFACE_3 = "#1B2432"   # chips, inputs
LINE = "#1E2735"        # divisoria sutil
LINE_HI = "#2B3749"     # divisoria destacada / borda de input

TXT = "#E9EFF8"
MUTE = "#9BA9BD"
FAINT = "#5E6C82"

CPU = "#4C9AFF"
GPU = "#31D583"
RAM = "#A78BFA"
DISK = "#F5A623"
NET = "#FF6B81"
FPS = "#22D3EE"
FRAME = "#F5A623"

OK = "#31D583"
WARN = "#F5A623"
BAD = "#FF5C5C"
CRIT = "#FF2D55"
IDLE = "#5E6C82"

FONT_UI = "Segoe UI"
FONT_DISPLAY = "Bahnschrift"
FONT_MONO = "Cascadia Mono"

RADIUS = 12
RADIUS_SM = 8
RADIUS_XS = 5
GAP = 12
PAD = 14

SCALE = 1.0


def scaled(px: float) -> int:
    """Converte um valor de design para pixels considerando a escala da UI."""
    return max(1, round(px * SCALE))


def set_scale(value: float) -> None:
    global SCALE
    SCALE = max(0.75, min(2.0, float(value)))


@dataclass(frozen=True)
class Accent:
    key: str
    label: str
    color: str


ACCENTS: dict[str, Accent] = {
    "cyan": Accent("cyan", "Ciano", "#22D3EE"),
    "blue": Accent("blue", "Azul", "#4C9AFF"),
    "green": Accent("green", "Verde", "#31D583"),
    "purple": Accent("purple", "Roxo", "#A78BFA"),
    "orange": Accent("orange", "Laranja", "#F5A623"),
    "red": Accent("red", "Vermelho", "#FF6B81"),
    "pink": Accent("pink", "Magenta", "#F472B6"),
}


def accent_color(key: str) -> str:
    return ACCENTS.get(key, ACCENTS["cyan"]).color


def rgba(hex_color: str, alpha: float) -> str:
    """#RRGGBB + alpha 0..1 -> 'rgba(r, g, b, a)' aceito pelo QSS."""
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r}, {g}, {b}, {alpha:.3f})"


def mix(color_a: str, color_b: str, t: float) -> str:
    """Interpola linearmente entre duas cores hex (t = 0 -> a, 1 -> b)."""
    t = max(0.0, min(1.0, t))
    a = color_a.lstrip("#")
    b = color_b.lstrip("#")
    out = []
    for i in (0, 2, 4):
        ca, cb = int(a[i:i + 2], 16), int(b[i:i + 2], 16)
        out.append(round(ca + (cb - ca) * t))
    return "#{:02X}{:02X}{:02X}".format(*out)


def _band(value: float | None, warn: float, bad: float, invert: bool = False) -> str:
    if value is None:
        return MUTE
    if invert:
        if value >= warn:
            return OK
        if value >= bad:
            return WARN
        return BAD
    if value < warn:
        return OK
    if value < bad:
        return WARN
    return BAD


def temp_color(t: float | None) -> str:
    if t is not None and t >= 92:
        return CRIT
    return _band(t, 65, 82)


def vram_temp_color(t: float | None) -> str:
    """GDDR mora quente: 68 graus parada e' normal e 85 nao e' noticia.

    A faixa geral (65/82/92) pintaria de vermelho uma placa que esta' bem, e um
    trilho de temperaturas alinhadas perde o sentido se cada linha estiver medida
    contra a regua errada.
    """
    return _band(t, 95, 105)


def dimm_temp_color(t: float | None, high: float | None = None,
                    critical: float | None = None) -> str:
    """Faixa do proprio pente: High Limit e Critical High vem de fabrica no SPD.

    Limiar chutado no app erra nas duas pontas — DDR5 a 55 ja' e' aviso do
    fabricante, e a mesma temperatura num processador seria ociosidade.
    """
    return _band(t, high or 55.0, critical or 85.0)


def load_color(pct: float | None) -> str:
    return _band(pct, 65, 88)


def fps_color(v: float | None) -> str:
    if v is None:
        return MUTE
    if v >= 100:
        return OK
    if v >= 55:
        return mix(OK, WARN, 0.35)
    if v >= 30:
        return WARN
    return BAD


def frametime_color(ms: float | None) -> str:
    return _band(ms, 12.0, 25.0)


def stutter_color(pct: float | None) -> str:
    return _band(pct, 1.0, 3.5)


def ping_color(ms: float | None) -> str:
    return _band(ms, 35, 80)


def loss_color(loss: float | None) -> str:
    if loss is None:
        return MUTE
    if loss <= 0:
        return OK
    return WARN if loss < 15 else BAD


def watt_color(w: float | None, warn: float, bad: float) -> str:
    return _band(w, warn, bad)


def score_color(score: float | None) -> str:
    """Notas de 0 a 100 onde mais alto e melhor."""
    return _band(score, 80, 55, invert=True)


DOMAIN_COLORS = {
    "cpu": CPU, "gpu": GPU, "ram": RAM, "disk": DISK, "net": NET, "fps": FPS,
}
