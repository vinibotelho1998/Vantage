"""Monitor de latencia e perda de pacotes via TCP connect (host configuravel)."""
from __future__ import annotations

import socket
import threading
import time


class PingMonitor:
    def __init__(self, host: str = "8.8.8.8", port: int = 53, samples: int = 5) -> None:
        self._host = host
        self._port = port
        self._samples = samples
        self._ms: int | None = None
        self._loss: int | None = None
        self._lock = threading.Lock()
        self._stop = threading.Event()

    def configure(self, host: str, port: int) -> None:
        with self._lock:
            self._host = host or self._host
            self._port = int(port) or self._port

    def _target(self) -> tuple[str, int]:
        with self._lock:
            return self._host, self._port

    def read(self) -> tuple[int | None, int | None]:
        with self._lock:
            return self._ms, self._loss

    def start(self) -> None:
        threading.Thread(target=self._loop, name="ping", daemon=True).start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.is_set():
            host, port = self._target()
            results: list[int | None] = []
            for _ in range(self._samples):
                if self._stop.is_set():
                    return
                try:
                    t = time.monotonic()
                    s = socket.create_connection((host, port), timeout=1.5)
                    s.close()
                    results.append(int((time.monotonic() - t) * 1000))
                except Exception:
                    results.append(None)
                time.sleep(0.2)
            ok = [r for r in results if r is not None]
            avg = int(sum(ok) / len(ok)) if ok else None
            loss = int((1 - len(ok) / self._samples) * 100)
            with self._lock:
                self._ms = avg
                self._loss = loss
            self._stop.wait(3)
