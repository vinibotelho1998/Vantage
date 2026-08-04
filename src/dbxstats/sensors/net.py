"""Latencia, jitter e perda de pacotes via TCP connect (nao exige ICMP nem admin)."""
from __future__ import annotations

import socket
import threading
import time
from collections import deque


class PingMonitor:
    """Mede RTT continuamente e mantem uma janela para calcular jitter e perda."""

    def __init__(self, host: str = "8.8.8.8", port: int = 53, samples: int = 5,
                 interval: float = 2.0) -> None:
        self._host = host
        self._port = port
        self._samples = samples
        self._interval = interval
        self._ms: float | None = None
        self._jitter: float | None = None
        self._loss: float | None = None
        self._best: float | None = None
        self._worst: float | None = None
        self._history: deque[float] = deque(maxlen=60)
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def configure(self, host: str, port: int) -> None:
        with self._lock:
            changed = host != self._host or int(port) != self._port
            self._host = host or self._host
            self._port = int(port) or self._port
            if changed:
                self._history.clear()
                self._best = self._worst = None

    def _target(self) -> tuple[str, int]:
        with self._lock:
            return self._host, self._port

    def read(self) -> dict:
        with self._lock:
            return {"ms": self._ms, "jitter": self._jitter, "loss": self._loss,
                    "best": self._best, "worst": self._worst}

    def history(self) -> list[float]:
        with self._lock:
            return list(self._history)

    def start(self) -> None:
        if self._thread is None:
            self._thread = threading.Thread(target=self._loop, name="ping", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.is_set():
            host, port = self._target()
            results: list[float | None] = []
            for _ in range(self._samples):
                if self._stop.is_set():
                    return
                results.append(_probe(host, port))
                self._stop.wait(0.15)
            self._publish(results)
            self._stop.wait(self._interval)

    def _publish(self, results: list[float | None]) -> None:
        ok = [r for r in results if r is not None]
        avg = sum(ok) / len(ok) if ok else None
        jitter = None
        if len(ok) > 1:
            jitter = sum(abs(ok[i] - ok[i - 1]) for i in range(1, len(ok))) / (len(ok) - 1)
        loss = round(100.0 * (1 - len(ok) / max(1, len(results))), 1)
        with self._lock:
            self._ms = None if avg is None else round(avg, 1)
            self._jitter = None if jitter is None else round(jitter, 1)
            self._loss = loss
            if avg is not None:
                self._history.append(round(avg, 1))
                self._best = avg if self._best is None else min(self._best, avg)
                self._worst = avg if self._worst is None else max(self._worst, avg)


def _probe(host: str, port: int, timeout: float = 1.5) -> float | None:
    try:
        t = time.perf_counter()
        with socket.create_connection((host, port), timeout=timeout):
            pass
        return (time.perf_counter() - t) * 1000.0
    except OSError:
        return None
