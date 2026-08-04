"""Metricas de frame a partir das amostras do PresentMon.

Um "sample" e uma tupla achatada (rapida de criar, barata de guardar):

    (t, ft, cpu_busy, gpu_busy, gpu_time, display_latency, displayed_time, click2photon)

Todos os tempos em milissegundos, exceto `t` (segundos, relogio do PresentMon).
Campos indisponiveis chegam como NaN.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from .series import mean, percentile, stdev

T, FT, CPU_BUSY, GPU_BUSY, GPU_TIME, DISP_LAT, DISPLAYED, C2P = range(8)

NAN = float("nan")

# Um frame e considerado "hitch" quando estoura este tempo absoluto (~20 fps instantaneo)
HITCH_MS = 50.0
# ...ou quando passa deste multiplo da mediana da sessao.
HITCH_FACTOR = 3.0
STUTTER_FACTOR = 1.5


def _finite(values) -> list[float]:
    return [v for v in values if v == v]  # NaN != NaN


def _fps(ms: float | None) -> float | None:
    if ms is None or ms != ms or ms <= 0:
        return None
    return 1000.0 / ms


def _worst_avg(ordered_desc: list[float], fraction: float) -> float | None:
    """Media dos piores `fraction` frametimes (definicao usada em reviews de hardware)."""
    if not ordered_desc:
        return None
    count = max(1, int(len(ordered_desc) * fraction))
    return sum(ordered_desc[:count]) / count


@dataclass
class FrameMetrics:
    """Resumo estatistico de uma janela de frames."""

    frames: int = 0
    duration: float = 0.0

    fps_now: float | None = None
    fps_avg: float | None = None
    fps_max: float | None = None
    fps_min: float | None = None
    low_1: float | None = None          # media dos 1% piores frames
    low_01: float | None = None         # media dos 0.1% piores frames
    p1: float | None = None             # percentil 99 do frametime, em fps
    p01: float | None = None
    p99_fps: float | None = None        # percentil 1 do frametime (melhores frames)

    ft_avg: float | None = None
    ft_med: float | None = None
    ft_min: float | None = None
    ft_max: float | None = None
    ft_std: float | None = None

    stutter_pct: float = 0.0
    hitches: int = 0
    dropped_pct: float = 0.0
    consistency: float | None = None    # 0..100, maior = frametime mais estavel
    smoothness: float | None = None     # 0..100, nota composta de experiencia

    cpu_busy: float | None = None
    gpu_busy: float | None = None
    gpu_wait: float | None = None
    render_latency: float | None = None
    click_to_photon: float | None = None

    bottleneck: str = "—"
    cpu_load_ratio: float | None = None
    gpu_load_ratio: float | None = None

    def as_dict(self) -> dict:
        return dict(self.__dict__)


@dataclass
class FrameStream:
    """Estado publico de um processo capturado."""

    pid: int = 0
    app: str = ""
    present_mode: str = ""
    sync_interval: int = -1
    last_seen: float = 0.0
    metrics: FrameMetrics = field(default_factory=FrameMetrics)

    @property
    def vsync(self) -> bool:
        return self.sync_interval is not None and self.sync_interval > 0


def window(samples: list[tuple], seconds: float) -> list[tuple]:
    """Corta o final da lista pelos ultimos `seconds` (a lista chega ordenada por t)."""
    if not samples or seconds <= 0:
        return samples
    cutoff = samples[-1][T] - seconds
    lo, hi = 0, len(samples)
    while lo < hi:
        mid = (lo + hi) // 2
        if samples[mid][T] < cutoff:
            lo = mid + 1
        else:
            hi = mid
    return samples[lo:]


def compute(samples: list[tuple], now_window: float = 1.0) -> FrameMetrics:
    """Calcula todas as metricas de uma janela ja recortada de frames."""
    m = FrameMetrics()
    n = len(samples)
    m.frames = n
    if n == 0:
        return m

    fts = [s[FT] for s in samples if s[FT] == s[FT] and s[FT] > 0]
    if len(fts) < 2:
        m.ft_avg = fts[0] if fts else None
        m.fps_avg = m.fps_now = _fps(m.ft_avg)
        return m

    m.duration = max(samples[-1][T] - samples[0][T], sum(fts) / 1000.0)

    ordered = sorted(fts)
    total = sum(fts)
    avg = total / len(fts)
    m.ft_avg = avg
    m.ft_med = percentile(ordered, 0.5)
    m.ft_min = ordered[0]
    m.ft_max = ordered[-1]
    m.ft_std = stdev(fts)

    m.fps_avg = _fps(avg)
    m.fps_max = _fps(ordered[0])
    m.fps_min = _fps(ordered[-1])

    desc = ordered[::-1]
    m.low_1 = _fps(_worst_avg(desc, 0.01))
    m.low_01 = _fps(_worst_avg(desc, 0.001))
    m.p1 = _fps(percentile(ordered, 0.99))
    m.p01 = _fps(percentile(ordered, 0.999))
    m.p99_fps = _fps(percentile(ordered, 0.01))

    m.fps_now = _fps(mean([s[FT] for s in window(samples, now_window)
                           if s[FT] == s[FT] and s[FT] > 0])) or m.fps_avg

    med = m.ft_med or avg
    stutter_limit = med * STUTTER_FACTOR
    hitch_limit = max(HITCH_MS, med * HITCH_FACTOR)
    stutters = hitches = 0
    for ms in fts:
        if ms > stutter_limit:
            stutters += 1
            if ms > hitch_limit:
                hitches += 1
    m.stutter_pct = round(100.0 * stutters / len(fts), 2)
    m.hitches = hitches

    dropped = sum(1 for s in samples if s[DISPLAYED] != s[DISPLAYED])
    m.dropped_pct = round(100.0 * dropped / n, 2)

    m.consistency = _consistency(m)
    m.smoothness = _smoothness(m)

    m.cpu_busy = _avg_col(samples, CPU_BUSY)
    m.gpu_busy = _avg_col(samples, GPU_BUSY)
    gpu_time = _avg_col(samples, GPU_TIME)
    if gpu_time is not None and m.gpu_busy is not None:
        m.gpu_wait = max(0.0, gpu_time - m.gpu_busy)
    m.render_latency = _avg_col(samples, DISP_LAT)
    m.click_to_photon = _avg_col(samples, C2P)

    _classify_bottleneck(m)
    return m


def _avg_col(samples: list[tuple], idx: int) -> float | None:
    vals = [s[idx] for s in samples if s[idx] == s[idx]]
    return sum(vals) / len(vals) if vals else None


def _consistency(m: FrameMetrics) -> float | None:
    """0..100 a partir do coeficiente de variacao do frametime."""
    if not m.ft_avg or m.ft_std is None or m.ft_avg <= 0:
        return None
    cv = m.ft_std / m.ft_avg
    return round(max(0.0, min(100.0, 100.0 * math.exp(-3.2 * cv))), 1)


def _smoothness(m: FrameMetrics) -> float | None:
    """Nota de experiencia: junta estabilidade, distancia do 1% low e engasgos."""
    if m.consistency is None or not m.fps_avg or not m.low_1:
        return None
    low_ratio = max(0.0, min(1.0, m.low_1 / m.fps_avg))
    penalty = min(35.0, m.stutter_pct * 6.0 + m.hitches * 2.5)
    score = 0.45 * m.consistency + 0.55 * (low_ratio * 100.0) - penalty
    return round(max(0.0, min(100.0, score)), 1)


def _classify_bottleneck(m: FrameMetrics) -> None:
    if not m.ft_avg or m.ft_avg <= 0:
        return
    if m.cpu_busy is not None:
        m.cpu_load_ratio = round(min(1.5, m.cpu_busy / m.ft_avg), 3)
    if m.gpu_busy is not None:
        m.gpu_load_ratio = round(min(1.5, m.gpu_busy / m.ft_avg), 3)
    gpu_r, cpu_r = m.gpu_load_ratio, m.cpu_load_ratio
    if gpu_r is None and cpu_r is None:
        return
    if gpu_r is not None and gpu_r >= 0.92:
        m.bottleneck = "GPU"
    elif cpu_r is not None and cpu_r >= 0.92:
        m.bottleneck = "CPU"
    elif ((gpu_r or 0) < 0.75 and (cpu_r or 0) < 0.75
            and (m.ft_std if m.ft_std is not None else 99.0) < 1.2):
        m.bottleneck = "Limitado (VSync/cap)"
    elif gpu_r is not None and cpu_r is not None:
        m.bottleneck = "GPU" if gpu_r > cpu_r + 0.08 else (
            "CPU" if cpu_r > gpu_r + 0.08 else "Balanceado")
    else:
        m.bottleneck = "Balanceado"


def histogram(frametimes: list[float], bins: int = 28) -> tuple[list[float], list[int]]:
    """Distribuicao de FPS instantaneo (util para ver spread e caudas)."""
    fps = [1000.0 / ms for ms in frametimes if ms == ms and ms > 0]
    if len(fps) < 2:
        return [], []
    lo, hi = min(fps), max(fps)
    if hi - lo < 1e-6:
        return [lo], [len(fps)]
    step = (hi - lo) / bins
    counts = [0] * bins
    for v in fps:
        idx = min(bins - 1, int((v - lo) / step))
        counts[idx] += 1
    centers = [lo + step * (i + 0.5) for i in range(bins)]
    return centers, counts


def percentile_curve(frametimes: list[float], points: int = 60) -> list[tuple[float, float]]:
    """Curva percentil -> FPS (0.1% ... 99%), como a do CapFrameX."""
    fts = sorted(_finite([f for f in frametimes if f > 0]))
    if len(fts) < 5:
        return []
    out: list[tuple[float, float]] = []
    for i in range(points):
        q = 0.001 + (0.999 - 0.001) * (i / (points - 1))
        ms = percentile(fts, 1.0 - q)
        if ms > 0:
            out.append((q * 100.0, 1000.0 / ms))
    return out


def verdict(m: FrameMetrics) -> str:
    """Frase curta sobre a qualidade da experiencia."""
    if not m.frames:
        return "Sem dados de frame."
    if m.smoothness is None:
        return "Coletando amostras…"
    if m.smoothness >= 85:
        return "Excelente — frametime consistente, praticamente sem engasgos."
    if m.smoothness >= 70:
        return "Bom — pequenas variacoes, imperceptiveis na maior parte do tempo."
    if m.smoothness >= 50:
        return "Irregular — o 1% low esta longe da media; da pra sentir."
    return "Ruim — stutter frequente. Vale investigar limites de energia, VRAM ou CPU."
