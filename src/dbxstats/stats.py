"""Acumulador min / media / max por metrica, thread-safe."""
from __future__ import annotations

import threading


class StatsTracker:
    def __init__(self) -> None:
        self._d: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def update(self, key: str, val) -> None:
        if val is None:
            return
        try:
            v = float(val)
        except (TypeError, ValueError):
            return
        with self._lock:
            e = self._d.get(key)
            if e is None:
                self._d[key] = [v, v, v, 1]
            else:
                if v < e[0]:
                    e[0] = v
                if v > e[1]:
                    e[1] = v
                e[2] += v
                e[3] += 1

    def get(self, key: str) -> tuple[float, float, float] | None:
        with self._lock:
            e = self._d.get(key)
            if not e:
                return None
            return e[0], e[2] / e[3], e[1]

    def fmt(self, key: str, decimals: int = 0, unit: str = "") -> str:
        r = self.get(key)
        if r is None:
            return ""
        mn, av, mx = r
        f = f".{decimals}f"
        return f"mín {mn:{f}} · méd {av:{f}} · máx {mx:{f}}{unit}"

    def clear(self) -> None:
        with self._lock:
            self._d.clear()
