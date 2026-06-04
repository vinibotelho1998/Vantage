"""Motor de FPS/frametime via PresentMon, lido por named pipe."""
from __future__ import annotations

import io
import os
import subprocess
import threading
import time
from collections import defaultdict, deque

from .. import log, paths

_log = log.get("fps")

PM_FALLBACK_URL = ("https://github.com/GameTechDev/PresentMon/releases/"
                   "download/v1.10.0/PresentMon-1.10.0-x64.exe")
PIPE_NAME = r"\\.\pipe\syspanel_fps"


class FpsEngine:
    def __init__(self, window: float = 0.5) -> None:
        self._window = window
        self._by_pid: dict[int, tuple] = {}
        self._sc: dict[tuple, tuple] = {}
        self._graph: dict[int, deque] = {}
        self._lock = threading.Lock()
        self._status = ""
        self._proc: subprocess.Popen | None = None
        self._reset_requested = False

    @property
    def status(self) -> str:
        return self._status

    def set_window(self, window: float) -> None:
        self._window = window

    def snapshot(self) -> dict[int, tuple]:
        with self._lock:
            return dict(self._by_pid)

    def graph_buffer(self, pid: int) -> list:
        with self._lock:
            return list(self._graph.get(pid, []))

    def reset(self) -> None:
        self._reset_requested = True
        with self._lock:
            self._by_pid.clear()
            self._sc.clear()
            self._graph.clear()

    def start(self) -> None:
        threading.Thread(target=self._loop, name="fps", daemon=True).start()

    def stop(self) -> None:
        if self._proc is not None:
            try:
                self._proc.terminate()
            except Exception:
                pass

    def _ensure_presentmon(self) -> str | None:
        exe = paths.presentmon_path()
        if exe.exists():
            return str(exe)
        self._status = "Baixando PresentMon..."
        try:
            import urllib.request
            url = _resolve_pm_url()
            tmp = str(exe) + ".tmp"
            urllib.request.urlretrieve(url, tmp)
            os.replace(tmp, exe)
            self._status = ""
            _log.info("PresentMon baixado em %s", exe)
            return str(exe)
        except Exception as e:
            self._status = "Falha ao baixar PresentMon"
            _log.warning("falha baixando PresentMon: %s", e)
            return None

    def _loop(self) -> None:
        import ctypes
        import msvcrt

        pm_exe = self._ensure_presentmon()
        if not pm_exe:
            return

        k32 = ctypes.windll.kernel32
        k32.CreateNamedPipeW.restype = ctypes.c_size_t
        k32.ConnectNamedPipe.restype = ctypes.c_bool
        invalid = (1 << (8 * ctypes.sizeof(ctypes.c_size_t))) - 1

        subprocess.call(["taskkill", "/F", "/IM", "presentmon.exe"],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(0.4)

        try:
            h_pipe = k32.CreateNamedPipeW(
                PIPE_NAME, 0x00000001, 0x00000000, 1, 65536, 65536, 0, None)
            if h_pipe == invalid:
                self._status = f"Pipe falhou ({k32.GetLastError()})"
                return

            self._status = "Aguardando PM..."
            proc = subprocess.Popen(
                [pm_exe, "-output_file", PIPE_NAME, "-no_top", "-stop_existing_session"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW)
            self._proc = proc

            connected = threading.Event()
            threading.Thread(
                target=lambda: (k32.ConnectNamedPipe(h_pipe, None), connected.set()),
                daemon=True).start()
            if not connected.wait(timeout=10):
                self._status = "Timeout: PM nao conectou"
                k32.CloseHandle(h_pipe)
                proc.terminate()
                return

            self._status = "Lendo FPS..."
            fd = msvcrt.open_osfhandle(h_pipe, os.O_RDONLY)
            f = io.TextIOWrapper(io.FileIO(fd, closefd=True), encoding="utf-8-sig")
            self._consume(proc, f)
            proc.wait()
        except Exception as e:
            self._status = f"Erro: {e}"
            _log.exception("erro no loop de FPS")
        finally:
            self._proc = None
            with self._lock:
                self._by_pid.clear()
                self._sc.clear()
                self._graph.clear()

    def _consume(self, proc, f) -> None:
        cols = _read_header(proc, f)
        if cols is None:
            return
        col_app, col_pid, col_sc, col_t, col_ms, col_disp = cols
        self._status = f"cols t={col_t} ms={col_ms} sc={col_sc}"

        frames = defaultdict(lambda: {"dq": deque(maxlen=600),
                                      "dq_disp": deque(maxlen=600),
                                      "dq_long": deque(maxlen=3000)})
        last_wall: dict[tuple, float] = {}
        now = time.monotonic
        need = max(col_app, col_pid, col_sc, col_t, col_ms, col_disp)

        while proc.poll() is None:
            if self._reset_requested:
                self._reset_requested = False
                frames.clear()
                last_wall.clear()
                with self._lock:
                    self._by_pid.clear()
                    self._sc.clear()
                    self._graph.clear()
            line = f.readline()
            if not line:
                time.sleep(0.005)
                continue
            line = line.strip()
            if not line:
                continue
            parts = line.split(",")
            if len(parts) <= need:
                continue
            try:
                app = os.path.basename(parts[col_app].strip())
                pid = int(parts[col_pid].strip())
                swap = parts[col_sc].strip()
                t_pm = float(parts[col_t].strip())
                ms_btw = float(parts[col_ms].strip())
                disp_raw = parts[col_disp].strip()
                ms_disp = float(disp_raw) if disp_raw else 0.0
                if ms_btw <= 0 or ms_btw > 5000:
                    continue
            except (ValueError, IndexError):
                continue

            self._ingest(frames, last_wall, now, pid, swap, app, t_pm, ms_btw, ms_disp)

    def _ingest(self, frames, last_wall, now, pid, swap, app, t_pm, ms_btw, ms_disp) -> None:
        key = (pid, swap)
        entry = frames[key]
        entry["dq"].append((t_pm, ms_btw))
        entry["dq_long"].append(ms_btw)
        if 0 < ms_disp < 5000:
            entry["dq_disp"].append((t_pm, ms_disp))
        last_wall[key] = now()

        cutoff = t_pm - self._window
        dq = entry["dq"]
        while dq and dq[0][0] < cutoff:
            dq.popleft()
        fps = _calc_fps(dq, ms_btw)
        fps_inst = round(1000 / ms_btw)

        dq_d = entry["dq_disp"]
        while dq_d and dq_d[0][0] < cutoff:
            dq_d.popleft()
        fps_disp = _calc_fps(dq_d, ms_disp) if ms_disp > 0 else fps

        dq_long = entry["dq_long"]
        if len(dq_long) >= 10:
            ordered = sorted(dq_long, reverse=True)
            n = len(ordered)
            fps_low = round(1000 / ordered[max(0, n // 100 - 1)])
            fps_01low = round(1000 / ordered[max(0, n // 1000 - 1)])
        else:
            fps_low = fps_01low = fps_inst

        sc_entry = (fps, app, now(), fps_disp, fps_inst, fps_low, fps_01low)
        with self._lock:
            self._sc[key] = sc_entry
            best = max((v for (p, _s), v in self._sc.items() if p == pid),
                       key=lambda x: x[0])
            self._by_pid[pid] = best
            if sc_entry[0] >= best[0]:
                if pid not in self._graph:
                    self._graph[pid] = deque(maxlen=7200)
                self._graph[pid].append(ms_btw)

        self._evict_stale(frames, last_wall, now())

    def _evict_stale(self, frames, last_wall, t_now) -> None:
        stale = [k for k, w in last_wall.items() if t_now - w > 3.0]
        for k in stale:
            p = k[0]
            del last_wall[k]
            frames.pop(k, None)
            with self._lock:
                self._sc.pop(k, None)
                remaining = [v for (pp, _), v in self._sc.items() if pp == p]
                if remaining:
                    self._by_pid[p] = max(remaining, key=lambda x: x[0])
                else:
                    self._by_pid.pop(p, None)
                    self._graph.pop(p, None)


def _calc_fps(dq, fallback_ms: float) -> int:
    if len(dq) < 2:
        return round(1000 / fallback_ms) if fallback_ms > 0 else 0
    avg_ms = sum(m for _, m in dq) / len(dq)
    return round(1000 / avg_ms) if avg_ms > 0 else 0


def _col(hdr: list[str], name: str, default: int) -> int:
    return next((i for i, h in enumerate(hdr) if name in h), default)


def _read_header(proc, f) -> tuple[int, int, int, int, int, int] | None:
    while True:
        header = f.readline()
        if header.strip():
            hdr = [h.strip().lower() for h in header.split(",")]
            return (_col(hdr, "application", 0), _col(hdr, "processid", 1),
                    _col(hdr, "swapchain", 2), _col(hdr, "timeinseconds", 9),
                    _col(hdr, "msbetweenpresents", 10), _col(hdr, "msbetweendisplaychange", 12))
        if proc.poll() is not None:
            return None
        time.sleep(0.05)


def _resolve_pm_url() -> str:
    import json
    import urllib.request
    try:
        req = urllib.request.Request(
            "https://api.github.com/repos/GameTechDev/PresentMon/releases",
            headers={"User-Agent": "DBXStats/2.0"})
        with urllib.request.urlopen(req, timeout=10) as r:
            releases = json.loads(r.read())
        for rel in releases:
            if not rel.get("tag_name", "").startswith("v1."):
                continue
            for asset in rel.get("assets", []):
                name = asset.get("name", "")
                if "x64" in name and name.endswith(".exe") and "PresentMon" in name:
                    return asset["browser_download_url"]
    except Exception:
        pass
    return PM_FALLBACK_URL
