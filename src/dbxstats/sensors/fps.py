"""Motor de captura de frames via PresentMon 2.x.

Arquitetura em tres camadas, cada uma isolada da outra:

  1. supervisor  — sobe o PresentMon, mantem a sessao viva e reinicia sozinho.
  2. leitor      — le o named pipe em blocos e so faz parsing (nenhuma conta).
  3. agregador   — recalcula percentis/estatisticas 4x por segundo, fora do caminho
                   critico. A UI le apenas o cache pronto.

Essa separacao e o que evita o motor "travar": o parser nunca fica lento por causa
de estatistica, e qualquer morte do PresentMon (sessao ETW derrubada, driver
reiniciado, jogo fechando o swapchain) e detectada e recuperada automaticamente.
"""
from __future__ import annotations

import io
import math
import os
import subprocess
import threading
import time
from collections import deque

from .. import log, paths
from ..core import frames as fr
from ..core.frames import FrameMetrics, FrameStream

_log = log.get("fps")

PM_FALLBACK_URL = ("https://github.com/GameTechDev/PresentMon/releases/"
                   "download/v2.5.1/PresentMon-2.5.1-x64.exe")

SESSION = "DBXStats"
# Processos que sempre apresentam quadros mas nunca sao "o jogo".
EXCLUDED = (
    "dwm.exe", "explorer.exe", "ShellExperienceHost.exe", "SearchHost.exe",
    "StartMenuExperienceHost.exe", "TextInputHost.exe", "WidgetService.exe",
    "ApplicationFrameHost.exe", "SystemSettings.exe", "LockApp.exe",
    "PhoneExperienceHost.exe", "Widgets.exe", "dbx-stats.exe", "DBXStats.exe",
)

MAX_SAMPLES = 60000        # ~7 min a 144 fps por swapchain
AGGREGATE_HZ = 4.0
STALE_STREAM_S = 5.0       # sem frames por tanto tempo -> some da lista
RETAIN_S = 20.0            # ...mas o historico so e descartado depois disso
WATCHDOG_S = 20.0          # jogo em foco sem nenhum frame -> reinicia o PresentMon
RESTART_BACKOFF = (1.0, 2.0, 4.0, 8.0, 15.0)

NAN = float("nan")

# ── mapeamento de colunas (aceita CSV v1 e v2) ────────────────────────────────
_COLUMNS_V2 = {
    "t": ("cpustarttime", "timeinseconds"),
    "ft": ("frametime", "msbetweenpresents"),
    "cpu_busy": ("cpubusy",),
    "gpu_busy": ("gpubusy",),
    "gpu_time": ("gputime",),
    "disp_lat": ("displaylatency", "msuntildisplayed"),
    "displayed": ("displayedtime", "msbetweendisplaychange"),
    "c2p": ("clicktophotonlatency",),
}
# O CPUStartTime do v2 vem em MILISSEGUNDOS; o TimeInSeconds do v1, em segundos.
# Medido no CSV real: captura de 20 s va de t=21 a t=19932, e o passo entre frames
# bate com o FrameTime em ms. Tratar isso como segundos encolhia a janela de
# analise em mil vezes — sobravam poucos quadros, e 1% e 0,1% low caiam no mesmo
# punhado de frames, saindo sempre iguais.
_TIME_SCALE = {"cpustarttime": 1e-3, "timeinseconds": 1.0}
# Escalas plausiveis para a autocalibracao (s, ms, us, ticks de QPC).
_SCALE_CANDIDATES = (1.0, 1e-3, 1e-6, 1e-7, 1e-9)
CALIBRATION_SAMPLES = 150

_COLUMNS_META = {
    "app": ("application",),
    "pid": ("processid",),
    "swap": ("swapchainaddress",),
    "mode": ("presentmode",),
    "sync": ("syncinterval",),
    "runtime": ("presentruntime", "runtime"),
}


class _Layout:
    """Indices das colunas do CSV, resolvidos a partir do cabecalho."""

    def __init__(self, header: str) -> None:
        cols = [c.strip().lower() for c in header.split(",")]
        index = {name: i for i, name in enumerate(cols)}
        self.idx: dict[str, int] = {}
        self.t_column = ""
        for key, names in {**_COLUMNS_META, **_COLUMNS_V2}.items():
            for name in names:
                if name in index:
                    self.idx[key] = index[name]
                    if key == "t":
                        self.t_column = name
                    break
        self.needed = max(self.idx.values()) if self.idx else 0
        self.ok = all(k in self.idx for k in ("app", "pid", "swap", "t", "ft"))
        self.t_scale = _TIME_SCALE.get(self.t_column, 1.0)

    def get(self, key: str) -> int:
        return self.idx.get(key, -1)


def _f(parts: list[str], i: int) -> float:
    """Converte uma celula do CSV; 'NA'/vazio viram NaN."""
    if i < 0:
        return NAN
    try:
        return float(parts[i])
    except (ValueError, IndexError):
        return NAN


class FpsEngine:
    """Captura frames e publica metricas prontas por processo."""

    def __init__(self, analysis_window: float = 60.0, now_window: float = 1.0) -> None:
        self._analysis_window = analysis_window
        self._now_window = now_window

        self._raw: dict[tuple[int, str], deque] = {}
        self._meta: dict[tuple[int, str], dict] = {}
        self._raw_lock = threading.Lock()

        self._streams: dict[int, FrameStream] = {}
        self._windows: dict[int, list[tuple]] = {}
        self._pub_lock = threading.Lock()

        self._stop = threading.Event()
        self._proc: subprocess.Popen | None = None
        self._proc_lock = threading.Lock()
        self._threads: list[threading.Thread] = []

        self._status = "parado"
        self._restarts = 0
        self._last_frame_at = 0.0
        self._expected_pid: int | None = None
        self._expected_since = 0.0
        self._force_restart = threading.Event()
        self._use_v1 = False
        self._consecutive_failures = 0

        self._capture_pid: int | None = None
        self._capture: list[tuple] = []
        self._capture_active = False

        self._t_scale = 1.0
        self._cal_done = True
        self._cal_prev: dict[tuple[int, str], float] = {}
        self._cal_ratios: list[float] = []

    # ── ciclo de vida ────────────────────────────────────────────────────────
    def start(self) -> None:
        if self._threads:
            return
        self._stop.clear()
        for target, name in ((self._supervise, "fps-supervisor"),
                             (self._aggregate_loop, "fps-aggregator")):
            t = threading.Thread(target=target, name=name, daemon=True)
            t.start()
            self._threads.append(t)

    def stop(self) -> None:
        self._stop.set()
        self._kill_process()
        self._cleanup_session()
        self._threads.clear()

    @property
    def status(self) -> str:
        return self._status

    @property
    def restarts(self) -> int:
        return self._restarts

    @property
    def running(self) -> bool:
        with self._proc_lock:
            return self._proc is not None and self._proc.poll() is None

    # ── configuracao ─────────────────────────────────────────────────────────
    def set_windows(self, analysis: float | None = None, now: float | None = None) -> None:
        if analysis:
            self._analysis_window = max(5.0, float(analysis))
        if now:
            self._now_window = max(0.2, float(now))

    def expect(self, pid: int | None) -> None:
        """Informa qual processo deveria estar produzindo frames (alimenta o watchdog)."""
        if pid != self._expected_pid:
            self._expected_pid = pid
            self._expected_since = time.monotonic()

    def restart(self) -> None:
        """Reinicio manual da captura (menu / configuracoes)."""
        self._force_restart.set()
        self._kill_process()

    # ── leitura publica ──────────────────────────────────────────────────────
    def snapshot(self) -> dict[int, FrameStream]:
        with self._pub_lock:
            return dict(self._streams)

    def stream(self, pid: int | None) -> FrameStream | None:
        if pid is None:
            return None
        with self._pub_lock:
            return self._streams.get(pid)

    def samples(self, pid: int | None) -> list[tuple]:
        if pid is None:
            return []
        with self._pub_lock:
            return self._windows.get(pid, [])

    def frametimes(self, pid: int | None, seconds: float | None = None) -> list[float]:
        data = self.samples(pid)
        if seconds:
            data = fr.window(data, seconds)
        return [s[fr.FT] for s in data if s[fr.FT] == s[fr.FT]]

    def apps(self) -> list[tuple[int, str, float]]:
        """(pid, nome, fps) de tudo que esta apresentando agora."""
        out = []
        for pid, st in self.snapshot().items():
            out.append((pid, st.app, st.metrics.fps_avg or 0.0))
        return sorted(out, key=lambda x: -x[2])

    def reset(self) -> None:
        with self._raw_lock:
            self._raw.clear()
            self._meta.clear()
        with self._pub_lock:
            self._streams.clear()
            self._windows.clear()

    # ── captura de benchmark ─────────────────────────────────────────────────
    def capture_start(self, pid: int) -> None:
        with self._raw_lock:
            self._capture = []
            self._capture_pid = pid
            self._capture_active = True

    def capture_stop(self) -> list[tuple]:
        with self._raw_lock:
            self._capture_active = False
            return list(self._capture)

    def capture_peek(self) -> int:
        with self._raw_lock:
            return len(self._capture)

    @property
    def capturing(self) -> bool:
        return self._capture_active

    # ── supervisor ───────────────────────────────────────────────────────────
    def _supervise(self) -> None:
        exe = self._ensure_presentmon()
        if not exe:
            self._status = "PresentMon indisponivel"
            _log.error("PresentMon nao encontrado em %s e o download falhou; "
                       "captura desligada", paths.presentmon_path())
            return
        attempt = 0
        while not self._stop.is_set():
            started = time.monotonic()
            try:
                self._run_session(exe)
            except Exception as e:
                _log.exception("sessao do PresentMon falhou: %s", e)
                self._status = f"erro: {e}"
            if self._stop.is_set():
                break
            lived = time.monotonic() - started
            attempt = 0 if lived > 30 else min(attempt + 1, len(RESTART_BACKOFF) - 1)
            self._restarts += 1
            delay = RESTART_BACKOFF[attempt]
            self._status = f"reiniciando captura em {delay:.0f}s"
            _log.info("PresentMon caiu apos %.1fs; reiniciando em %.0fs", lived, delay)
            self._stop.wait(delay)

    def _run_session(self, exe: str) -> None:
        pipe_name = rf"\\.\pipe\dbxstats_fps_{os.getpid()}_{self._restarts}"
        self._force_restart.clear()
        self.reset()
        self._cleanup_session()
        handle = _create_pipe(pipe_name)
        if handle is None:
            self._status = "falha criando pipe"
            _log.warning("nao consegui criar o pipe %s", pipe_name)
            self._stop.wait(3.0)
            return
        proc = None
        try:
            self._status = "iniciando PresentMon"
            proc = subprocess.Popen(
                self._command(exe, pipe_name),
                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                stdin=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
            with self._proc_lock:
                self._proc = proc

            if not _wait_connect(handle, proc, timeout=12.0):
                self._status = "PresentMon nao conectou"
                # A queixa do PresentMon e' a unica pista quando ele nao sobe:
                # "access denied" (sessao presa / sem admin) contra "in use"
                # sao problemas diferentes, e sem isso o log fica mudo.
                _log.warning("PresentMon nao conectou (saida %s): %s",
                             proc.poll(), _stderr_tail(proc))
                self._note_failure()
                return
            self._consecutive_failures = 0
            self._status = "capturando"
            self._read_pipe(handle, proc)
            handle = None  # consumido pelo FileIO
        finally:
            if handle is not None:
                _close_handle(handle)
            if proc is not None:
                _terminate(proc)
            with self._proc_lock:
                self._proc = None
            self._cleanup_session()

    def _command(self, exe: str, pipe_name: str) -> list[str]:
        # input tracking fica ligado de proposito: e o que da a latencia clique -> tela
        cmd = [exe, "--output_file", pipe_name, "--no_console_stats",
               "--stop_existing_session", "--session_name", SESSION]
        cmd.append("--v1_metrics" if self._use_v1 else "--v2_metrics")
        for name in EXCLUDED:
            cmd += ["--exclude", name]
        return cmd

    def _note_failure(self) -> None:
        self._consecutive_failures += 1
        if self._consecutive_failures >= 2 and not self._use_v1:
            self._use_v1 = True
            _log.warning("PresentMon nao aceitou --v2_metrics; usando --v1_metrics")

    # ── leitor ───────────────────────────────────────────────────────────────
    def _read_pipe(self, handle: int, proc: subprocess.Popen) -> None:
        import msvcrt
        fd = msvcrt.open_osfhandle(handle, os.O_RDONLY)
        raw = io.FileIO(fd, closefd=True)
        pending = b""
        layout: _Layout | None = None
        try:
            while not self._stop.is_set() and not self._force_restart.is_set():
                chunk = raw.read(1 << 16)
                if not chunk:
                    break
                pending += chunk
                lines = pending.split(b"\n")
                pending = lines.pop()
                if layout is None:
                    while lines:
                        head = lines.pop(0).decode("utf-8-sig", "ignore").strip()
                        if not head:
                            continue
                        layout = _Layout(head)
                        if not layout.ok:
                            _log.warning("cabecalho inesperado do PresentMon: %s", head[:200])
                            return
                        self._begin_calibration(layout)
                        _log.info("PresentMon conectado (%d colunas, tempo em %s)",
                                  len(layout.idx), layout.t_column or "?")
                        break
                    if layout is None:
                        continue
                if lines:
                    self._ingest(layout, lines)
        except OSError as e:
            _log.info("leitura do pipe encerrada: %s", e)
        finally:
            self._force_restart.clear()
            try:
                raw.close()
            except OSError:
                pass
            if proc.poll() is None:
                _terminate(proc)

    def _ingest(self, layout: _Layout, lines: list[bytes]) -> None:
        idx = layout.idx
        i_app, i_pid, i_swap = idx["app"], idx["pid"], idx["swap"]
        i_mode, i_sync, i_rt = layout.get("mode"), layout.get("sync"), layout.get("runtime")
        i_t, i_ft = idx["t"], idx["ft"]
        i_cb, i_gb = layout.get("cpu_busy"), layout.get("gpu_busy")
        i_gt, i_dl = layout.get("gpu_time"), layout.get("disp_lat")
        i_dp, i_c2p = layout.get("displayed"), layout.get("c2p")
        need = layout.needed

        scale = self._t_scale
        calibrando = not self._cal_done
        cal_rows: list[tuple[tuple[int, str], float, float]] = []

        batch: list[tuple[tuple[int, str], tuple, str, str, int]] = []
        for line in lines:
            if not line:
                continue
            parts = line.decode("latin-1").rstrip("\r").split(",")
            if len(parts) <= need:
                continue
            try:
                pid = int(parts[i_pid])
                ft = float(parts[i_ft])
                t = float(parts[i_t])
            except ValueError:
                continue
            if ft <= 0.0 or ft > 10_000.0:
                continue
            key = (pid, parts[i_swap])
            if calibrando:
                cal_rows.append((key, t, ft))
            sample = (t * scale, ft, _f(parts, i_cb), _f(parts, i_gb), _f(parts, i_gt),
                      _f(parts, i_dl), _f(parts, i_dp), _f(parts, i_c2p))
            app = os.path.basename(parts[i_app]).strip()
            sync = -1
            if i_sync >= 0:
                try:
                    sync = int(parts[i_sync])
                except ValueError:
                    sync = -1
            mode = parts[i_mode].strip() if i_mode >= 0 else ""
            runtime = parts[i_rt].strip() if i_rt >= 0 else ""
            batch.append((key, sample, app, f"{mode}|{runtime}", sync))

        if cal_rows:
            self._calibrate(cal_rows)
            if self._t_scale != scale:   # a calibracao corrigiu a unidade no lote
                fator = self._t_scale / scale
                batch = [(k, (sm[0] * fator,) + sm[1:], a, m, y)
                         for k, sm, a, m, y in batch]
        if not batch:
            return
        now = time.monotonic()
        with self._raw_lock:
            for key, sample, app, modes, sync in batch:
                buf = self._raw.get(key)
                if buf is None:
                    buf = deque(maxlen=MAX_SAMPLES)
                    self._raw[key] = buf
                buf.append(sample)
                mode, _, runtime = modes.partition("|")
                self._meta[key] = {"app": app, "mode": mode, "runtime": runtime,
                                   "sync": sync, "seen": now}
                if self._capture_active and key[0] == self._capture_pid:
                    self._capture.append(sample)
        self._last_frame_at = now

    # ── unidade da coluna de tempo ───────────────────────────────────────────
    def _begin_calibration(self, layout: _Layout) -> None:
        """Assume a unidade indicada pelo cabecalho e prepara a conferencia."""
        self._t_scale = layout.t_scale
        self._cal_done = False
        self._cal_prev.clear()
        self._cal_ratios.clear()

    def _calibrate(self, rows: list[tuple[tuple[int, str], float, float]]) -> None:
        """Confere a unidade real comparando o avanco do relogio com o frametime.

        Em qualquer versao do PresentMon, o tempo entre dois presents da mesma
        swapchain e' exatamente o FrameTime — entao a razao entre os dois revela a
        unidade, mesmo que uma versao futura mude o padrao ou alguem ligue
        --qpc_time. Errar essa unidade encolhe a janela de analise e faz 1% e
        0,1% low colapsarem no mesmo numero.
        """
        for key, t_raw, ft in rows:
            prev = self._cal_prev.get(key)
            self._cal_prev[key] = t_raw
            if prev is None:
                continue
            delta = t_raw - prev
            if delta <= 0.0 or ft <= 0.0:
                continue
            self._cal_ratios.append(delta / ft)     # unidades de tempo por ms de frame
            if len(self._cal_ratios) >= CALIBRATION_SAMPLES:
                self._finish_calibration()
                return

    def _finish_calibration(self) -> None:
        ratios = sorted(self._cal_ratios)
        mediana = ratios[len(ratios) // 2]
        self._cal_done = True
        self._cal_prev.clear()
        self._cal_ratios.clear()
        if mediana <= 0.0:
            return
        medido = 1e-3 / mediana                     # unidades -> segundos
        melhor = min(_SCALE_CANDIDATES, key=lambda c: abs(math.log10(c / medido)))
        if abs(math.log10(melhor / medido)) > math.log10(3.0):
            _log.warning("nao consegui confirmar a unidade do relogio do PresentMon "
                         "(fator medido %.3g); mantendo %.3g", medido, self._t_scale)
            return
        if melhor == self._t_scale:
            return
        _log.warning("unidade da coluna de tempo corrigida: %.3g -> %.3g s por unidade",
                     self._t_scale, melhor)
        self._t_scale = melhor
        self.reset()                                # o pouco que entrou veio errado

    # ── agregador ────────────────────────────────────────────────────────────
    def _aggregate_loop(self) -> None:
        period = 1.0 / AGGREGATE_HZ
        while not self._stop.wait(period):
            try:
                self._recompute()
                self._watchdog()
            except Exception:
                _log.exception("erro agregando metricas de frame")

    def _recompute(self) -> None:
        now = time.monotonic()
        with self._raw_lock:
            # PresentMon entrega o CSV em rajadas: uma pausa curta nao pode apagar
            # o historico, so tira o processo da lista de ativos.
            for k in [k for k, m in self._meta.items() if now - m["seen"] > RETAIN_S]:
                self._raw.pop(k, None)
                self._meta.pop(k, None)
            snapshot = [(k, list(v), dict(self._meta[k]))
                        for k, v in self._raw.items()
                        if k in self._meta and now - self._meta[k]["seen"] <= STALE_STREAM_S]

        best: dict[int, tuple[int, list[tuple], dict]] = {}
        for (pid, _swap), samples, meta in snapshot:
            windowed = fr.window(samples, self._analysis_window)
            current = best.get(pid)
            if current is None or len(windowed) > current[0]:
                best[pid] = (len(windowed), windowed, meta)

        streams: dict[int, FrameStream] = {}
        windows: dict[int, list[tuple]] = {}
        for pid, (_count, windowed, meta) in best.items():
            metrics: FrameMetrics = fr.compute(windowed, self._now_window)
            streams[pid] = FrameStream(
                pid=pid, app=meta["app"], present_mode=meta["mode"],
                sync_interval=meta["sync"], last_seen=meta["seen"], metrics=metrics)
            windows[pid] = windowed

        with self._pub_lock:
            self._streams = streams
            self._windows = windows

    def _watchdog(self) -> None:
        """Reinicia a captura se o jogo esperado nao produz frame nenhum."""
        pid = self._expected_pid
        if pid is None or not self.running:
            return
        with self._pub_lock:
            alive = pid in self._streams
        if alive:
            self._expected_since = time.monotonic()
            return
        if time.monotonic() - self._expected_since > WATCHDOG_S:
            _log.warning("watchdog: %ds sem frames do pid %s; reiniciando PresentMon",
                         int(WATCHDOG_S), pid)
            self._status = "watchdog: reiniciando"
            self._expected_since = time.monotonic()
            self.restart()

    # ── processo auxiliar ────────────────────────────────────────────────────
    def _kill_process(self) -> None:
        with self._proc_lock:
            proc = self._proc
        if proc is not None:
            _terminate(proc)

    def _cleanup_session(self) -> None:
        for verb in ("stop", "delete"):
            try:
                subprocess.call(["logman", verb, SESSION, "-ets"],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                creationflags=subprocess.CREATE_NO_WINDOW)
            except Exception:
                pass

    def _ensure_presentmon(self) -> str | None:
        exe = paths.presentmon_path()
        if exe.exists():
            return str(exe)
        self._status = "baixando PresentMon"
        try:
            import urllib.request
            tmp = str(exe) + ".tmp"
            urllib.request.urlretrieve(_resolve_pm_url(), tmp)
            os.replace(tmp, exe)
            _log.info("PresentMon baixado em %s", exe)
            return str(exe)
        except Exception as e:
            _log.warning("falha baixando PresentMon: %s", e)
            return None


# ── helpers win32 ─────────────────────────────────────────────────────────────
def _create_pipe(name: str) -> int | None:
    import ctypes
    k32 = ctypes.windll.kernel32
    k32.CreateNamedPipeW.restype = ctypes.c_void_p
    invalid = (1 << (8 * ctypes.sizeof(ctypes.c_void_p))) - 1
    size = 4 << 20
    handle = k32.CreateNamedPipeW(name, 0x00000001 | 0x00080000,  # INBOUND | FIRST_INSTANCE
                                  0x00000000, 1, size, size, 0, None)
    if not handle or handle == invalid:
        _log.warning("CreateNamedPipeW falhou (%d)", k32.GetLastError())
        return None
    return int(handle)


def _stderr_tail(proc: subprocess.Popen, limit: int = 300) -> str:
    """Ultima queixa do processo, sem travar se ele ainda estiver vivo."""
    if proc.stderr is None:
        return "(sem saida de erro)"
    if proc.poll() is None:
        return "(ainda rodando)"
    try:
        texto = proc.stderr.read().decode("latin-1", "ignore").strip()
    except (OSError, ValueError):
        return "(nao consegui ler)"
    return " ".join(texto.split())[-limit:] or "(nada)"


def _wait_connect(handle: int, proc: subprocess.Popen, timeout: float) -> bool:
    import ctypes
    k32 = ctypes.windll.kernel32
    k32.ConnectNamedPipe.restype = ctypes.c_bool
    done = threading.Event()

    def _connect() -> None:
        try:
            k32.ConnectNamedPipe(ctypes.c_void_p(handle), None)
        finally:
            done.set()

    threading.Thread(target=_connect, name="fps-connect", daemon=True).start()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if done.wait(0.2):
            return True
        if proc.poll() is not None:
            return False
    return False


def _close_handle(handle: int) -> None:
    import ctypes
    try:
        ctypes.windll.kernel32.CloseHandle(ctypes.c_void_p(handle))
    except Exception:
        pass


def _terminate(proc: subprocess.Popen) -> None:
    try:
        if proc.poll() is None:
            proc.terminate()
            proc.wait(timeout=3)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def _resolve_pm_url() -> str:
    import json
    import urllib.request
    try:
        req = urllib.request.Request(
            "https://api.github.com/repos/GameTechDev/PresentMon/releases",
            headers={"User-Agent": "DBXStats/3.0"})
        with urllib.request.urlopen(req, timeout=10) as r:
            releases = json.loads(r.read())
        for rel in releases:
            if not rel.get("tag_name", "").startswith("v2."):
                continue
            for asset in rel.get("assets", []):
                name = asset.get("name", "")
                if "x64" in name and name.endswith(".exe") and "PresentMon" in name:
                    return asset["browser_download_url"]
    except Exception:
        pass
    return PM_FALLBACK_URL
