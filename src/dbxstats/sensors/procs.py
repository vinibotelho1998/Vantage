"""Monitor de processos: top consumidores de CPU/RAM, atualizado numa cadencia propria."""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass

import psutil

from .. import log

_log = log.get("procs")

# Processos de sistema que poluem o ranking sem serem acionaveis pelo usuario.
_HIDE = {"system idle process", "memory compression"}


@dataclass(frozen=True)
class ProcInfo:
    pid: int
    name: str
    cpu: float
    ram_mb: float
    threads: int
    is_game: bool = False


class ProcessMonitor:
    def __init__(self, interval: float = 2.5, limit: int = 40) -> None:
        self._interval = interval
        self._limit = limit
        self._procs: list[ProcInfo] = []
        self._count = 0
        self._threads_total = 0
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._cores = psutil.cpu_count(logical=True) or 1
        self._game_pids: set[int] = set()

    def start(self) -> None:
        if self._thread is None:
            self._thread = threading.Thread(target=self._loop, name="procs", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def set_game_pids(self, pids) -> None:
        with self._lock:
            self._game_pids = set(pids or ())

    def snapshot(self) -> list[ProcInfo]:
        with self._lock:
            return list(self._procs)

    def totals(self) -> tuple[int, int]:
        with self._lock:
            return self._count, self._threads_total

    def _loop(self) -> None:
        for p in psutil.process_iter(["pid"]):
            try:
                p.cpu_percent(None)
            except psutil.Error:
                continue
        while not self._stop.wait(self._interval):
            try:
                self._collect()
            except Exception:
                _log.exception("erro coletando processos")

    def _collect(self) -> None:
        with self._lock:
            games = set(self._game_pids)
        rows: list[ProcInfo] = []
        threads_total = 0
        count = 0
        for p in psutil.process_iter(["pid", "name", "memory_info", "num_threads"]):
            try:
                info = p.info
                name = info["name"] or "?"
                if name.lower() in _HIDE:
                    continue
                count += 1
                threads_total += info["num_threads"] or 0
                cpu = p.cpu_percent(None) / self._cores
                mem = info["memory_info"]
                rows.append(ProcInfo(
                    pid=info["pid"], name=name, cpu=round(cpu, 1),
                    ram_mb=round((mem.rss if mem else 0) / 1024 ** 2, 1),
                    threads=info["num_threads"] or 0, is_game=info["pid"] in games))
            except (psutil.Error, AttributeError, TypeError):
                continue
        rows.sort(key=lambda r: (-r.cpu, -r.ram_mb))
        with self._lock:
            self._procs = rows[:self._limit]
            self._count = count
            self._threads_total = threads_total


def process_name(pid: int | None) -> str:
    if not pid:
        return ""
    try:
        return psutil.Process(pid).name()
    except psutil.Error:
        return ""


def process_started_at(pid: int | None) -> float | None:
    if not pid:
        return None
    try:
        return time.time() - psutil.Process(pid).create_time()
    except psutil.Error:
        return None
