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

SESSION_PREFIX = "DBXStats"
SESSION = f"{SESSION_PREFIX}_{os.getpid()}"
"""Nome da sessao ETW, unico por processo.

Ja' foi a constante "DBXStats" para todo mundo, e duas copias do app abertas ao
mesmo tempo viravam uma briga sem fim: cada uma subia o PresentMon com
--stop_existing_session e derrubava a sessao da outra. O sintoma era o
PresentMon ficar vivo sem nunca conectar no pipe. Com o pid no nome, duas
instancias se ignoram.
"""
# Processos que apresentam quadros mas nunca sao "o jogo". Sem essa lista o
# terminal, o navegador e o Discord entram na disputa — e como o painel escolhe
# quem tem mais quadros, o "jogo em foco" acabava sendo o Warp ou o Chrome.
EXCLUDED = (
    # shell do Windows
    "dwm.exe", "explorer.exe", "ShellExperienceHost.exe", "SearchHost.exe",
    "StartMenuExperienceHost.exe", "TextInputHost.exe", "WidgetService.exe",
    "ApplicationFrameHost.exe", "SystemSettings.exe", "LockApp.exe",
    "PhoneExperienceHost.exe", "Widgets.exe",
    # o proprio app
    "dbx-stats.exe", "DBXStats.exe",
    # navegadores
    "chrome.exe", "msedge.exe", "firefox.exe", "brave.exe", "opera.exe",
    "opera_gx.exe", "vivaldi.exe",
    # terminais e editores
    "WindowsTerminal.exe", "warp.exe", "powershell.exe", "pwsh.exe", "cmd.exe",
    "Code.exe", "devenv.exe", "notepad.exe",
    # comunicacao, midia e lojas
    "Discord.exe", "Spotify.exe", "Telegram.exe", "WhatsApp.exe", "obs64.exe",
    "steamwebhelper.exe", "EpicGamesLauncher.exe", "Battle.net.exe",
)

MAX_SAMPLES = 60000        # ~7 min a 144 fps por swapchain
AGGREGATE_HZ = 4.0
STALE_STREAM_S = 5.0       # sem frames por tanto tempo -> some da lista
RETAIN_S = 20.0            # ...mas o historico so e descartado depois disso
WATCHDOG_S = 20.0          # jogo em foco sem nenhum frame -> reinicia o PresentMon
STUCK_S = 45.0             # captura sem sinal de vida nenhum -> supervisor travado
REVIVE_S = 120.0           # supervisor sem dar uma volta -> aposenta e sobe outro
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
        self._alive_at = 0.0
        """Ultimo sinal de vida da captura: frame novo ou troca de sessao."""
        self._reader: io.FileIO | None = None
        """Pipe em leitura. Fechar daqui e' o que solta um `read` travado."""
        self._expected_pid: int | None = None
        self._expected_since = 0.0
        self._force_restart = threading.Event()
        self._use_v1 = False
        self._consecutive_failures = 0
        self._gen = 0
        self._loop_at = time.monotonic()
        """Ultima volta completa do supervisor. Se para de andar, ele travou.

        Comeca no relogio de agora, e nao em zero: um motor recem-criado nao
        pode parecer travado ha' uma eternidade.
        """

        self._capture_pid: int | None = None
        self._session_rec = None
        self._session_pid: int | None = None
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
        self._spawn_supervisor()
        t = threading.Thread(target=self._aggregate_loop, name="fps-aggregator", daemon=True)
        t.start()
        self._threads.append(t)

    def _spawn_supervisor(self) -> None:
        """Sobe (ou substitui) a thread que cuida do PresentMon.

        A geracao serve para aposentar a thread antiga: se ela estiver travada
        num desmonte e acordar depois, ve' que nao e' mais a da vez e sai, em
        vez de subir um segundo PresentMon disputando a mesma sessao.
        """
        self._gen += 1
        geracao = self._gen
        self._loop_at = time.monotonic()
        self._threads = [t for t in self._threads
                         if not isinstance(t, threading.Thread) or t.is_alive()]
        t = threading.Thread(target=self._supervise, args=(geracao,),
                             name=f"fps-supervisor-{geracao}", daemon=True)
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

    # ── partida inteira ──────────────────────────────────────────────────────
    def session_start(self, pid: int) -> None:
        """Comeca a acompanhar uma partida do inicio ao fim.

        Roda junto com o resto sem atrapalhar: o custo por frame e' constante e
        o tamanho nao cresce com a duracao, entao pode ficar ligado a partida
        toda sem virar peso na maquina que esta' jogando.
        """
        rec = fr.SessionRecorder()
        rec.started_at = time.monotonic()
        with self._raw_lock:
            self._session_pid = pid
            self._session_rec = rec

    def session_follow(self, pid: int) -> None:
        """Passa a seguir outro processo, mantendo o que ja' foi medido.

        Atalho de loja abre o cliente, e o jogo sobe depois com outro nome —
        quando descobrimos quem e' de verdade, a gravacao continua nele.
        """
        with self._raw_lock:
            if self._session_rec is not None:
                self._session_pid = pid

    def session_stop(self) -> dict | None:
        with self._raw_lock:
            rec, self._session_rec = self._session_rec, None
            self._session_pid = None
        if rec is None:
            return None
        rec.ended_at = time.monotonic()
        return rec.result()

    def session_peek(self) -> int:
        with self._raw_lock:
            return self._session_rec.count if self._session_rec is not None else 0

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
    def _supervise(self, geracao: int = 1) -> None:
        exe = self._ensure_presentmon()
        if not exe:
            self._status = "PresentMon indisponivel"
            _log.error("PresentMon nao encontrado em %s e o download falhou; "
                       "captura desligada", paths.presentmon_path())
            return
        sweep_stale_sessions()
        attempt = 0
        while not self._stop.is_set() and geracao == self._gen:
            self._loop_at = time.monotonic()
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
            _log.info("subindo PresentMon (tentativa %d, %s)",
                      self._restarts + 1, "v1" if self._use_v1 else "v2")
            proc = subprocess.Popen(
                self._command(exe, pipe_name),
                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                stdin=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
            with self._proc_lock:
                self._proc = proc

            if not _wait_connect(handle, proc, self._stop, self._force_restart,
                                 self._aguardando_jogo):
                handle = None   # quem desiste do connect nao fecha; ver _wait_connect
                self._status = "PresentMon nao conectou"
                # A queixa do PresentMon e' a unica pista quando ele nao sobe:
                # "access denied" (sessao presa / sem admin) contra "in use"
                # sao problemas diferentes, e sem isso o log fica mudo. Encerrar
                # antes de ler e' o que fecha o stderr — com ele vivo a leitura
                # so' podia devolver "(ainda rodando)", que nao diz nada.
                _terminate(proc)
                erro = _stderr_tail(proc)
                _log.warning("PresentMon nao conectou (saida %s): %s", proc.poll(), erro)
                self._note_failure(erro)
                return
            self._consecutive_failures = 0
            self._alive_at = time.monotonic()
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

    def _aguardando_jogo(self) -> None:
        """Sinal de vida enquanto o PresentMon espera algo para reportar.

        Sem isso o watchdog mataria uma captura perfeitamente saudavel: ficar
        quieto no desktop e' o comportamento certo dele, nao travamento.
        """
        self._alive_at = time.monotonic()
        self._status = "aguardando um jogo"

    def _note_failure(self, erro: str = "") -> None:
        self._consecutive_failures += 1
        queixa = erro.lower()

        # Sessao ETW deixada para tras por uma execucao anterior faz todo
        # StartTrace novo voltar "access denied", e a captura nunca mais sobe.
        # Ja' aconteceu de valer meia hora sem FPS e sem overlay, resolvido na
        # mao com `logman`. Agora o proprio motor limpa e tenta de novo.
        if "access denied" in queixa or "in use" in queixa or "already" in queixa:
            _log.warning("sessao de rastreamento bloqueada; varrendo sessoes orfas")
            sweep_stale_sessions()
            return

        # Cair para v1 so' quando o PresentMon realmente recusa a opcao. Contar
        # falha seguida como "ele nao aceita --v2_metrics" degradava as metricas
        # de vez por causa de problema que nada tinha a ver com isso.
        if not self._use_v1 and ("unrecognized option" in queixa or "invalid" in queixa):
            self._use_v1 = True
            _log.warning("PresentMon nao aceitou --v2_metrics; usando --v1_metrics")

    # ── leitor ───────────────────────────────────────────────────────────────
    def _read_pipe(self, handle: int, proc: subprocess.Popen) -> None:
        import msvcrt
        fd = msvcrt.open_osfhandle(handle, os.O_RDONLY)
        raw = io.FileIO(fd, closefd=True)
        self._reader = raw
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
            self._reader = None
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
                # Gravador da partida inteira: uma soma e um indice por frame,
                # sem guardar amostra nenhuma. Ver frames.SessionRecorder.
                if self._session_rec is not None and key[0] == self._session_pid:
                    self._session_rec.add(sample[1])
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
        """Reinicia a captura se ela parar de dar sinal de vida."""
        self._rescue_if_stuck()
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

    def _rescue_if_stuck(self) -> None:
        """Solta a captura quando ela para sem morrer.

        O leitor bloqueia num `read` do pipe. Se o PresentMon some sem fechar a
        ponta dele — sessao ETW roubada por outra instancia, processo morto a
        forca — esse read nunca volta, e o supervisor fica parado para sempre
        sem log nenhum. Fechar o pipe daqui e' o que faz o read levantar erro e
        o ciclo recomecar.
        """
        if self._stop.is_set():
            return
        agora = time.monotonic()
        vivo = max(self._alive_at, self._last_frame_at)
        if not vivo:
            self._alive_at = agora
            return
        if agora - vivo < STUCK_S:
            return
        _log.warning("captura sem sinal de vida ha %.0fs (processo %s); reiniciando",
                     agora - vivo, "vivo" if self.running else "morto")
        self._alive_at = agora
        self._status = "destravando captura"
        self._force_restart.set()
        leitor, self._reader = self._reader, None
        if leitor is not None:
            try:
                leitor.close()
            except OSError:
                pass
        self._kill_process()

        # Fechar o pipe e matar o processo so' adianta se o supervisor ainda
        # estiver de pe' para recomecar. Quando e' ele que travou, esse aviso se
        # repetia a cada 45s para sempre — 111 vezes no log, meia hora sem
        # captura. Se ele nao deu nem uma volta nesse tempo todo, esta' preso:
        # aposenta e sobe outro.
        if self._threads and agora - self._loop_at > REVIVE_S:
            _log.warning("supervisor parado ha %.0fs; subindo outro", agora - self._loop_at)
            self._spawn_supervisor()

    # ── processo auxiliar ────────────────────────────────────────────────────
    def _kill_process(self) -> None:
        with self._proc_lock:
            proc = self._proc
        if proc is not None:
            _terminate(proc)

    def _cleanup_session(self) -> None:
        """Derruba a sessao ETW que tenha sobrado de uma execucao anterior."""
        for verb in ("stop", "delete"):
            _run_bounded(["logman", verb, SESSION, "-ets"], 8.0, f"logman {verb}")

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


def _run_bounded(cmd: list[str], seconds: float, what: str) -> None:
    """Roda um comando auxiliar sem nunca segurar quem chamou.

    subprocess.run(timeout=...) parece resolver e nao resolve: quando o prazo
    estoura ele mata o filho e *espera* o wait terminar. Se o processo estiver
    preso no kernel — `logman` com uma sessao ETW em estado ruim faz isso — esse
    wait nunca volta, e o supervisor congela sem escrever uma linha no log. Foi
    exatamente assim que a captura morreu por meia hora com o watchdog gritando
    "reiniciando" 111 vezes e nada acontecendo.

    Aqui a espera tem fim de verdade: passado o prazo mandamos matar e seguimos
    em frente sem esperar resposta.
    """
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                stdin=subprocess.DEVNULL,
                                creationflags=subprocess.CREATE_NO_WINDOW)
    except Exception as e:
        _log.debug("nao consegui rodar %s: %s", what, e)
        return
    fim = time.monotonic() + seconds
    while time.monotonic() < fim:
        if proc.poll() is not None:
            return
        time.sleep(0.1)
    _log.warning("%s nao terminou em %.0fs; abandonando", what, seconds)
    try:
        proc.kill()
    except Exception:
        pass


def sweep_stale_sessions() -> None:
    """Apaga sessoes ETW deixadas por instancias antigas do app.

    Como o nome agora leva o pid, uma copia que morreu de forma feia deixa a
    sessao dela para tras — e sessao ETW e' recurso global e limitado. Cada uma
    e' derrubada em processo separado para que uma travada nao impeca as outras.
    """
    saida: list[str] = []

    def _consultar() -> None:
        try:
            r = subprocess.run(["logman", "query", "-ets"], capture_output=True,
                               creationflags=subprocess.CREATE_NO_WINDOW)
            saida.append(r.stdout.decode("latin-1", "ignore"))
        except Exception:
            pass

    t = threading.Thread(target=_consultar, name="fps-sweep", daemon=True)
    t.start()
    t.join(8.0)
    if not saida:
        return
    alvos = []
    for linha in saida[0].splitlines():
        nome = linha.split()[0] if linha.split() else ""
        if not _orfa(nome):
            continue
        alvos.append(nome)
        # "tentando", e nao "removendo": o comando nao espera resposta, entao
        # afirmar a remocao aqui e' contar o que nao se sabe.
        _log.info("tentando remover sessao ETW orfa: %s", nome)
        _run_bounded(["logman", "stop", nome, "-ets"], 8.0, f"logman stop {nome}")
        _run_bounded(["logman", "delete", nome, "-ets"], 8.0, f"logman delete {nome}")

    if alvos:
        _conferir_remocao(alvos)


def _conferir_remocao(alvos: list[str]) -> None:
    """Diz se a limpeza pegou, e nomeia o suspeito quando nao pega.

    Sem esta conferencia o log ficava afirmando "removendo sessao ETW orfa" a
    cada 15 segundos enquanto nada acontecia — e quem lesse concluiria que o
    problema era outro. Custou uma hora de diagnostico na direcao errada.

    Quando a sessao resiste, a causa quase sempre e' outra copia do app ainda no
    ar segurando o recurso: `logman stop` volta "acesso negado" mesmo com
    privilegio de administrador, o que faz parecer falta de permissao. Dizer
    isso na hora poupa a caca ao erro errado.
    """
    restantes: list[str] = []

    def _consultar() -> None:
        try:
            r = subprocess.run(["logman", "query", "-ets"], capture_output=True,
                               creationflags=subprocess.CREATE_NO_WINDOW)
            texto = r.stdout.decode("latin-1", "ignore")
            restantes.extend(n for n in alvos if n in texto)
        except Exception:                                    # noqa: BLE001
            pass

    t = threading.Thread(target=_consultar, name="fps-sweep-check", daemon=True)
    t.start()
    t.join(8.0)

    if not restantes:
        _log.info("sessoes ETW orfas removidas: %s", ", ".join(alvos))
        return

    # A causa muda conforme haja ou nao outra copia viva, e o conselho tambem.
    # Dizer sempre "feche as outras copias" manda procurar o que nao existe —
    # com nenhuma aberta, a sessao ja' esta' num estado que nem administrador
    # nem SYSTEM desfazem, e so' o reinicio limpa.
    outras = _outras_copias()
    if outras:
        _log.warning(
            "a sessao ETW %s resistiu a remocao. Ha' outra copia do DBX Stats "
            "aberta (pid %s) segurando ela: feche todas e a limpeza passa. Nao "
            "e' falta de permissao, mesmo que o logman diga 'acesso negado'.",
            ", ".join(restantes), ", ".join(str(p) for p in outras))
        return
    _log.warning(
        "a sessao ETW %s resistiu a remocao e nao ha' outra copia do app "
        "aberta. Ela ficou num estado que nem administrador nem SYSTEM "
        "desfazem — a captura de quadros so' volta reiniciando o Windows. "
        "Acontece quando o app e' encerrado a forca com a captura ativa.",
        ", ".join(restantes))


def _outras_copias() -> list[int]:
    """Pids de outras instancias do app, sem contar esta.

    E' o que separa "feche a outra janela" de "so' o reinicio resolve": os dois
    sintomas sao identicos no log, e o conselho errado custa a caca ao problema
    errado.
    """
    try:
        import psutil
    except ImportError:
        return []
    eu = os.getpid()
    achados = []
    for proc in psutil.process_iter(["pid", "name"]):
        nome = (proc.info.get("name") or "").lower()
        if proc.info["pid"] != eu and nome in ("dbxstats.exe", "pythonw.exe"):
            achados.append(proc.info["pid"])
    return achados


def _orfa(nome: str) -> bool:
    """Sessao que sobrou de outra execucao e precisa sair da frente.

    O nome exato SESSION_PREFIX entra na conta de proposito: e' como as versoes
    antigas chamavam a sessao, e uma delas ficou para tras rodando. Enquanto
    estava viva, todo StartTrace novo voltava "access denied" — meia hora sem
    FPS e sem overlay. Varrer so' os nomes com pid deixaria justamente ela.
    """
    if nome == SESSION:
        return False
    return nome == SESSION_PREFIX or nome.startswith(SESSION_PREFIX + "_")


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


def _esperar_conexao(done, proc, stop, force, esperando=None) -> bool:
    """Espera a conexao chegar, enquanto o processo estiver vivo.

    Separado do resto para poder ser exercitado sem um pipe de verdade: e' aqui
    que mora a regra que estava errada — silencio com processo vivo nao e'
    falha, e' o PresentMon esperando um jogo aparecer.
    """
    while True:
        if done.wait(0.2):
            return True
        if proc.poll() is not None:      # morreu de verdade: ai' sim e' falha
            return False
        if stop.is_set() or force.is_set():
            return False
        if esperando is not None:
            esperando()


def _wait_connect(handle: int, proc: subprocess.Popen, stop, force, esperando=None) -> bool:
    """Espera o PresentMon abrir a outra ponta do pipe.

    Espera o tempo que for preciso, enquanto o processo estiver vivo. Havia um
    prazo de 12 segundos aqui, e ele estava errado: o PresentMon so' abre o
    arquivo de saida quando tem o primeiro quadro para escrever, e a lista de
    exclusoes do app tira justamente tudo o que apresenta quadros no desktop —
    navegador, terminal, o proprio app. Sem jogo aberto ele fica calado, de
    propria vontade, e o prazo transformava esse silencio saudavel em "falhou":
    o processo era morto e ressuscitado a cada quinze segundos, para sempre.
    Medido: com as 37 exclusoes, o arquivo nem chega a ser criado; sem elas,
    1815 linhas em seis segundos.

    Quem desiste aqui NAO deve fechar o handle depois: ConnectNamedPipe e'
    sincrono e, quando desistimos, a thread auxiliar continua parada dentro do
    kernel segurando esse mesmo handle. Fechar por fora um handle com I/O
    pendente de outra thread e' exatamente o tipo de coisa que congela o
    supervisor sem deixar rastro no log. Entao cancelamos a operacao e, dando ou
    nao certo, o fechamento fica com a thread presa — ela fecha quando acordar.
    """
    import ctypes
    k32 = ctypes.windll.kernel32
    k32.ConnectNamedPipe.restype = ctypes.c_bool
    k32.OpenThread.restype = ctypes.c_void_p
    done = threading.Event()
    abandonado = threading.Event()
    tid: list[int] = []
    trava = threading.Lock()
    fechado = [False]

    def _fechar_uma_vez() -> None:
        # Fechar duas vezes e' pior do que vazar: o numero pode ja' pertencer a
        # outro handle quando o segundo fechamento chegar.
        with trava:
            if fechado[0]:
                return
            fechado[0] = True
        _close_handle(handle)

    def _connect() -> None:
        tid.append(int(k32.GetCurrentThreadId()))
        try:
            k32.ConnectNamedPipe(ctypes.c_void_p(handle), None)
        finally:
            done.set()
            if abandonado.is_set():
                _fechar_uma_vez()

    threading.Thread(target=_connect, name="fps-connect", daemon=True).start()
    if _esperar_conexao(done, proc, stop, force, esperando):
        return True

    abandonado.set()
    if tid:
        THREAD_TERMINATE = 0x0001   # o acesso que CancelSynchronousIo exige
        h = k32.OpenThread(THREAD_TERMINATE, False, tid[0])
        if h:
            k32.CancelSynchronousIo(ctypes.c_void_p(h))
            k32.CloseHandle(ctypes.c_void_p(h))
    if done.wait(1.0):
        _fechar_uma_vez()   # cobre a corrida: a thread pode ter saido antes do aviso
        return False
    _log.warning("thread do pipe nao respondeu ao cancelamento; handle abandonado")
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
