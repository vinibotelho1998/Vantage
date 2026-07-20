"""Design tokens e mapeamentos de cor: fonte unica de verdade do visual."""
from __future__ import annotations

from dataclasses import dataclass

BG = "#0D1117"
BG_ALT = "#0B0E14"
CARD = "#161B22"
CARD_HI = "#1C2230"
LINE = "#21262D"
LINE_HI = "#2D333B"

TXT = "#E6EDF3"
MUTE = "#8B949E"
FAINT = "#636E7B"

CPU = "#58A6FF"
RAM = "#BC8CFF"
GPU = "#3FB950"
DISK = "#D29922"
NET = "#FF7B72"

OK = "#3FB950"
WARN = "#D29922"
BAD = "#F85149"
IDLE = "#636E7B"

FONT_UI = "Segoe UI"
FONT_MONO = "Cascadia Mono"
FONT_DISPLAY = "Bahnschrift"
RADIUS = 14
RADIUS_SM = 8

SCALE = 1.0


def scaled(px: float) -> int:
    return round(px * SCALE)


@dataclass(frozen=True)
class Accent:
    key: str
    label: str
    color: str


ACCENTS: dict[str, Accent] = {
    "blue": Accent("blue", "Azul", "#58A6FF"),
    "green": Accent("green", "Verde", "#3FB950"),
    "purple": Accent("purple", "Roxo", "#BC8CFF"),
    "orange": Accent("orange", "Laranja", "#D29922"),
    "red": Accent("red", "Vermelho", "#FF7B72"),
    "cyan": Accent("cyan", "Ciano", "#39C5CF"),
}


def accent_color(key: str) -> str:
    return ACCENTS.get(key, ACCENTS["blue"]).color


def temp_color(t: float | None) -> str:
    if t is None:
        return MUTE
    if t < 65:
        return OK
    if t < 80:
        return WARN
    return BAD


def load_color(pct: float | None) -> str:
    if pct is None:
        return MUTE
    if pct < 60:
        return OK
    if pct < 85:
        return WARN
    return BAD


def fps_color(v: float | None) -> str:
    if v is None:
        return MUTE
    if v >= 60:
        return OK
    if v >= 30:
        return WARN
    return BAD


def stutter_color(pct: float | None) -> str:
    if pct is None:
        return MUTE
    if pct < 1:
        return OK
    if pct < 3:
        return WARN
    return BAD


def ping_color(ms: float | None) -> str:
    if ms is None:
        return MUTE
    if ms < 40:
        return OK
    if ms < 80:
        return WARN
    return BAD


def watt_color(w: float | None, warn: float, bad: float) -> str:
    if w is None:
        return MUTE
    if w < warn:
        return OK
    if w < bad:
        return WARN
    return BAD


def loss_color(loss: float | None) -> str:
    if loss is None:
        return MUTE
    if loss == 0:
        return OK
    if loss < 20:
        return WARN
    return BAD
