"""Formatacao de grandezas para exibicao. Sempre tolerante a None."""
from __future__ import annotations

DASH = "—"

_RATE_UNITS = ((1 << 30, "GB/s", 2), (1 << 20, "MB/s", 1), (1 << 10, "KB/s", 0))
_SIZE_UNITS = ((1 << 40, "TB", 2), (1 << 30, "GB", 1), (1 << 20, "MB", 0), (1 << 10, "KB", 0))


def rate(bytes_per_s: float | None) -> str:
    if bytes_per_s is None:
        return DASH
    v = float(bytes_per_s)
    for factor, unit, dec in _RATE_UNITS:
        if v >= factor:
            return f"{v / factor:.{dec}f} {unit}"
    return f"{v:.0f} B/s"


def size(num_bytes: float | None) -> str:
    if num_bytes is None:
        return DASH
    v = float(num_bytes)
    for factor, unit, dec in _SIZE_UNITS:
        if v >= factor:
            return f"{v / factor:.{dec}f} {unit}"
    return f"{v:.0f} B"


def gib(value_gib: float | None, decimals: int = 1) -> str:
    return DASH if value_gib is None else f"{value_gib:.{decimals}f} GB"


def mib_pair(used_mib: float | None, total_mib: float | None) -> str:
    if used_mib is None or total_mib is None:
        return DASH
    return f"{used_mib / 1024:.1f} / {total_mib / 1024:.1f} GB"


def clock(mhz: float | None) -> str:
    if not mhz:
        return DASH
    return f"{mhz / 1000:.2f} GHz" if mhz >= 1000 else f"{mhz:.0f} MHz"


def mhz(value: float | None) -> str:
    return DASH if not value else f"{value:.0f} MHz"


def temp(celsius: float | None, decimals: int = 0) -> str:
    return DASH if celsius is None else f"{celsius:.{decimals}f} °C"


def watts(w: float | None, decimals: int = 1) -> str:
    return DASH if w is None else f"{w:.{decimals}f} W"


def percent(v: float | None, decimals: int = 0) -> str:
    return DASH if v is None else f"{v:.{decimals}f}%"


def rpm(v: float | None) -> str:
    return DASH if not v else f"{v:.0f} RPM"


def ms(v: float | None, decimals: int = 1) -> str:
    return DASH if v is None else f"{v:.{decimals}f} ms"


def integer(v: float | None) -> str:
    return DASH if v is None else f"{v:.0f}"


def duration(seconds: float | None) -> str:
    if seconds is None:
        return DASH
    total = int(seconds)
    days, rem = divmod(total, 86400)
    h, rem = divmod(rem, 3600)
    m, s = divmod(rem, 60)
    if days:
        return f"{days}d {h:02d}:{m:02d}"
    return f"{h:02d}:{m:02d}:{s:02d}"


def compact(v: float | None, decimals: int = 1) -> str:
    if v is None:
        return DASH
    a = abs(v)
    if a >= 1_000_000_000:
        return f"{v / 1e9:.{decimals}f}B"
    if a >= 1_000_000:
        return f"{v / 1e6:.{decimals}f}M"
    if a >= 1_000:
        return f"{v / 1e3:.{decimals}f}k"
    return f"{v:.0f}"


def sensor_value(value: float | None, unit: str) -> str:
    """Formata um sensor generico da arvore do LibreHardwareMonitor."""
    if value is None:
        return DASH
    decimals = {"°C": 1, "V": 3, "W": 1, "%": 1, "MHz": 0, "RPM": 0, "GB": 2, "MB": 0}.get(unit, 1)
    return f"{value:.{decimals}f} {unit}".strip()
