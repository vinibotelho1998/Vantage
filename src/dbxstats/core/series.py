"""Series temporais em memoria e acumuladores min/med/max, thread-safe."""
from __future__ import annotations

import math
import threading
from collections import deque

NAN = float("nan")


def percentile(sorted_values: list[float], q: float) -> float:
    """Percentil por interpolacao linear. `sorted_values` precisa estar ordenado."""
    n = len(sorted_values)
    if n == 0:
        return NAN
    if n == 1:
        return sorted_values[0]
    pos = max(0.0, min(1.0, q)) * (n - 1)
    lo = int(pos)
    hi = min(lo + 1, n - 1)
    frac = pos - lo
    return sorted_values[lo] * (1 - frac) + sorted_values[hi] * frac


def mean(values) -> float:
    values = list(values)
    return sum(values) / len(values) if values else NAN


def stdev(values) -> float:
    values = list(values)
    n = len(values)
    if n < 2:
        return 0.0
    m = sum(values) / n
    return math.sqrt(sum((v - m) ** 2 for v in values) / (n - 1))


class Series:
    """Buffer circular de amostras numericas para graficos (gaps viram NaN)."""

    __slots__ = ("_buf", "_maxlen")

    def __init__(self, maxlen: int = 480) -> None:
        self._maxlen = maxlen
        self._buf: deque[float] = deque(maxlen=maxlen)

    def push(self, value) -> None:
        try:
            v = float(value)
        except (TypeError, ValueError):
            v = NAN
        self._buf.append(v)

    def extend_hold(self) -> None:
        """Repete a ultima amostra (usado quando uma fonte fica temporariamente muda)."""
        self._buf.append(self._buf[-1] if self._buf else NAN)

    def clear(self) -> None:
        self._buf.clear()

    def resize(self, maxlen: int) -> None:
        if maxlen == self._maxlen:
            return
        self._maxlen = maxlen
        self._buf = deque(self._buf, maxlen=maxlen)

    def values(self) -> list[float]:
        return list(self._buf)

    def finite(self) -> list[float]:
        return [v for v in self._buf if not math.isnan(v)]

    @property
    def last(self) -> float | None:
        for v in reversed(self._buf):
            if not math.isnan(v):
                return v
        return None

    @property
    def capacity(self) -> int:
        return self._maxlen

    def __len__(self) -> int:
        return len(self._buf)

    def span(self) -> tuple[float, float] | None:
        vals = self.finite()
        if not vals:
            return None
        return min(vals), max(vals)


class History:
    """Conjunto nomeado de series alimentado a cada ciclo de coleta."""

    def __init__(self, maxlen: int = 480) -> None:
        self._maxlen = maxlen
        self._series: dict[str, Series] = {}
        self._lock = threading.Lock()

    def series(self, key: str) -> Series:
        with self._lock:
            s = self._series.get(key)
            if s is None:
                s = Series(self._maxlen)
                self._series[key] = s
            return s

    def push(self, key: str, value) -> None:
        self.series(key).push(value)

    def push_many(self, mapping: dict) -> None:
        for key, value in mapping.items():
            self.push(key, value)

    def values(self, key: str) -> list[float]:
        return self.series(key).values()

    def last(self, key: str):
        return self.series(key).last

    def keys(self) -> list[str]:
        with self._lock:
            return list(self._series)

    def resize(self, maxlen: int) -> None:
        """Ajusta a profundidade do historico preservando as amostras existentes."""
        with self._lock:
            self._maxlen = maxlen
            for s in self._series.values():
                s.resize(maxlen)

    def clear(self) -> None:
        with self._lock:
            for s in self._series.values():
                s.clear()


class Accumulator:
    """min / media / max / ultimo valor por chave, acumulado desde o ultimo reset."""

    def __init__(self) -> None:
        self._d: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def update(self, key: str, value) -> None:
        if value is None:
            return
        try:
            v = float(value)
        except (TypeError, ValueError):
            return
        if math.isnan(v):
            return
        with self._lock:
            e = self._d.get(key)
            if e is None:
                self._d[key] = [v, v, v, 1.0, v]
            else:
                if v < e[0]:
                    e[0] = v
                if v > e[1]:
                    e[1] = v
                e[2] += v
                e[3] += 1
                e[4] = v

    def get(self, key: str) -> tuple[float, float, float] | None:
        """Retorna (min, media, max) ou None se a chave nunca recebeu amostra."""
        with self._lock:
            e = self._d.get(key)
            if not e:
                return None
            return e[0], e[2] / e[3], e[1]

    def last(self, key: str) -> float | None:
        with self._lock:
            e = self._d.get(key)
            return e[4] if e else None

    def count(self, key: str) -> int:
        with self._lock:
            e = self._d.get(key)
            return int(e[3]) if e else 0

    def fmt(self, key: str, decimals: int = 0, unit: str = "") -> str:
        r = self.get(key)
        if r is None:
            return ""
        mn, av, mx = r
        f = f".{decimals}f"
        return f"mín {mn:{f}} · méd {av:{f}} · máx {mx:{f}}{unit}"

    def keys(self) -> list[str]:
        with self._lock:
            return list(self._d)

    def clear(self, key: str | None = None) -> None:
        with self._lock:
            if key is None:
                self._d.clear()
            else:
                self._d.pop(key, None)


class Ema:
    """Media movel exponencial para suavizar leituras nervosas (watts, fps instantaneo)."""

    __slots__ = ("_alpha", "_value")

    def __init__(self, alpha: float = 0.3) -> None:
        self._alpha = alpha
        self._value: float | None = None

    def push(self, value: float | None) -> float | None:
        if value is None:
            return self._value
        v = float(value)
        self._value = v if self._value is None else self._value + self._alpha * (v - self._value)
        return self._value

    @property
    def value(self) -> float | None:
        return self._value

    def reset(self) -> None:
        self._value = None
