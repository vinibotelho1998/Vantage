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

# ── fluidez ───────────────────────────────────────────────────────────────────
# O que se sente como fluidez e' a cadencia entre quadros vizinhos, nao o espalhamento
# em torno da media da janela: um jogo que cai de 120 para 60 fps ao longo de um minuto
# tem desvio padrao enorme e mesmo assim parece liso, enquanto 8/16/8/16 ms com a mesma
# media e' insuportavel. Dai a nota sair da variacao entre quadros consecutivos.
SMOOTH_FLOOR_MS = 0.2
"""Trepidacao que nao conta. 0,2 ms e' menos de 5% do refresh mais curto de um monitor
comum (4,2 ms a 240 Hz), entao o quadro cai na mesma janela de tela de qualquer jeito.
Sem esse piso um vsync travado a 144 fps — que oscila decimos de ms so' pelo
escalonador do Windows — perdia mais de dez pontos por um tremor invisivel."""
SMOOTH_K = 2.2
"""Decaimento da nota com a trepidacao relativa a mediana: 5% -> 90, 10% -> 80,
20% -> 64, 50% -> 33. Exponencial para nunca estourar 0..100 nem saturar cedo."""
SMOOTH_JUMP_WEIGHT = 6.0
"""Peso da fracao de quadros que quebram a cadencia (mesmo criterio do SessionRecorder:
quadro 1,5x mais lento que o anterior). 5% dos quadros pulando tira 30% da nota.
Fracao, e nao contagem: contagem crescia com o tamanho da janela e fazia a mesma
captura valer notas diferentes a 10 s e a 5 min."""
SMOOTH_EVENT_W = 0.08
"""Peso da severidade dos solavancos, em "medianas de atraso por segundo".

Um pico de 45 ms numa base de 7 ms custa ~5,5 medianas; um por segundo derruba a
nota para ~65. Dez vezes menos frequente, para ~92. A escala e' continua de
proposito: a punicao anterior contava quadros acima de 50 ms absolutos, e um
pico de 49 ms valia 96 contra 19 de um pico de 51 ms."""
SMOOTH_HITCH_WEIGHT = 0.8
"""Peso das travadas por segundo. Aqui a unidade e' tempo, nao quadros: uma pausa de
60 ms incomoda igual a 30 ou a 240 fps, e o que se percebe e' de quanto em quanto tempo
ela acontece. Uma travada a cada 10 s tira 8% da nota; uma a cada dois segundos, 40% —
que e' onde o texto do veredito deixa de dizer "imperceptivel"."""
SMOOTH_PENALTY_MAX = 0.9
"""Teto da punicao por eventos, para a nota nao zerar so' por eles — com a captura
travada de verdade a trepidacao ja' derruba o resto sozinha."""
SMOOTH_MIN_FRAMES = 30
"""Menos que isso a mediana das diferencas e' chute; melhor a interface dizer que ainda
esta' coletando do que mostrar uma nota que muda de 40 para 90 no tique seguinte."""

# ── gargalo ───────────────────────────────────────────────────────────────────
# O criterio e' o do proprio PresentMon: por quadro, quem trabalhou mais — CPUBusy ou
# GPUBusy. Comparar cada um contra o frametime medio, como se fazia antes, mistura
# quadros de regimes diferentes e ignora que os dois numeros nascem do mesmo quadro.
BOTTLENECK_CPU = "CPU"
BOTTLENECK_GPU = "GPU"
BOTTLENECK_BALANCED = "Equilibrado"
BOTTLENECK_CAP = "VSync/cap"
BOTTLENECK_NA = "indisponível"
BOTTLENECK_NONE = "—"
BOTTLENECK_MARGIN = 0.10
"""Diferenca relativa minima entre CPUBusy e GPUBusy para o quadro ter dono. Abaixo
disso os dois terminam praticamente juntos e o quadro entra como empate."""
BOTTLENECK_LEAD = 0.60
"""Fatia dos quadros que um lado precisa dominar para virar veredito. Uma zona de
empate larga e uma decisao por maioria — e nao por diferenca de medias — e' o que
impede o rotulo de piscar entre CPU e GPU a cada tique de 250 ms."""
BOTTLENECK_SLACK = 0.75
"""Quando nem CPU nem GPU ocupam esta fracao do quadro, ninguem e' gargalo: o quadro
esta' esperando vsync ou limitador de fps."""
BOTTLENECK_MIN_FRAMES = 60
"""Piso de amostra antes de opinar. No inicio da captura chegavam poucos quadros e o
veredito saia de dois ou tres deles — sempre errado, e ainda por cima confiante."""


def _finite(values) -> list[float]:
    return [v for v in values if v == v]  # NaN != NaN


def _fps(ms: float | None) -> float | None:
    if ms is None or ms != ms or ms <= 0:
        return None
    return 1000.0 / ms


def _worst_avg(ordered_desc: list[float], fraction: float) -> float | None:
    """Media dos piores `fraction` frametimes (definicao usada em reviews de hardware).

    Sem piso de amostras: forcar um minimo fazia 1% e 0,1% cairem no mesmo punhado
    de quadros em janela curta, e os dois numeros saiam identicos.
    """
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
    ft_jitter: float | None = None      # mediana de |ft[i] - ft[i-1]|, em ms

    stutter_pct: float = 0.0
    hitches: int = 0
    dropped_pct: float = 0.0
    consistency: float | None = None    # 0..100, maior = frametime mais estavel
    smoothness: float | None = None     # 0..100, qualidade da cadencia
    jump_pct: float = 0.0               # % de quadros 1,5x mais lentos que o anterior
    jump_severity: float = 0.0          # medianas de atraso somadas nos solavancos

    cpu_busy: float | None = None
    gpu_busy: float | None = None
    gpu_wait: float | None = None
    render_latency: float | None = None
    click_to_photon: float | None = None

    bottleneck: str = BOTTLENECK_NONE
    bottleneck_detail: str = ""
    cpu_load_ratio: float | None = None
    gpu_load_ratio: float | None = None
    cpu_bound_pct: float | None = None   # % de quadros em que a CPU terminou por ultimo
    gpu_bound_pct: float | None = None
    capped_pct: float | None = None      # % de quadros sem nenhum dos dois saturado

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

    m.ft_jitter, jumps, m.jump_severity = _pacing(fts, m.ft_med or 0.0)
    m.jump_pct = round(100.0 * jumps / len(fts), 2)
    m.consistency = _consistency(m)
    m.smoothness = _smoothness(m, len(fts))

    m.cpu_busy = _avg_col(samples, CPU_BUSY)
    m.gpu_busy = _avg_col(samples, GPU_BUSY)
    gpu_time = _avg_col(samples, GPU_TIME)
    if gpu_time is not None and m.gpu_busy is not None:
        m.gpu_wait = max(0.0, gpu_time - m.gpu_busy)
    m.render_latency = _avg_col(samples, DISP_LAT)
    m.click_to_photon = _avg_col(samples, C2P)

    _classify_bottleneck(m, samples)
    return m


def _avg_col(samples: list[tuple], idx: int) -> float | None:
    vals = [s[idx] for s in samples if s[idx] == s[idx]]
    return sum(vals) / len(vals) if vals else None


def _consistency(m: FrameMetrics) -> float | None:
    """0..100 a partir do coeficiente de variacao do frametime.

    Continua sendo a leitura classica de review (desvio padrao sobre media), e por
    isso mesmo mora ao lado do desvio padrao na interface. Nao alimenta mais a
    fluidez: por depender da media da janela inteira, um unico quadro de 200 ms
    entre dez mil derruba o numero e o devolve no tique seguinte, quando o quadro
    sai da janela — instabilidade que nao tem nada a ver com o que se sentiu.
    """
    if not m.ft_avg or m.ft_std is None or m.ft_avg <= 0:
        return None
    cv = m.ft_std / m.ft_avg
    return round(max(0.0, min(100.0, 100.0 * math.exp(-3.2 * cv))), 1)


def _pacing(fts: list[float], mediana: float) -> tuple[float, int, float]:
    """Trepidacao tipica, quantos quadros pulam, e o quanto os pulos custaram.

    Mediana das diferencas, e nao media: assim uma travada isolada nao contamina
    a medida da cadencia — ela e' contada a parte, como evento, que e' como se
    percebe.

    A severidade e' o terceiro numero e existe por causa de um degrau feio: a
    punicao saia de uma contagem de quadros acima de 50 ms absolutos, entao um
    pico de 49 ms valia nota 96 e um de 51 ms valia 19 — 77 pontos de diferenca
    por 2 ms. E pior, depois do degrau a nota subia de novo com picos maiores,
    porque so' a contagem importava. Aqui cada pulo entra pelo tamanho: quantas
    medianas ele custou a mais.
    """
    deltas: list[float] = []
    jumps = 0
    severidade = 0.0
    limite = mediana * STUTTER_FACTOR if mediana else 0.0
    prev = fts[0]
    for ms in fts[1:]:
        deltas.append(abs(ms - prev))
        if ms > prev * STUTTER_FACTOR:
            jumps += 1
        if limite and ms > limite:
            severidade += (ms - mediana) / mediana
        prev = ms
    deltas.sort()
    return percentile(deltas, 0.5), jumps, severidade


def _smoothness(m: FrameMetrics, n: int) -> float | None:
    """0..100 de qualidade da cadencia: trepidacao continua x solavancos pontuais.

    Mede ritmo, nao velocidade. Uma queda lenta de 120 para 60 fps nao tira pontos
    daqui — ela aparece inteira no proprio FPS e nos lows; o que esta nota responde
    e' o quanto o intervalo entre quadros muda de um para o outro.

    Os dois fatores multiplicam em vez de somar: cada um vale uma fracao do que
    sobrou (0..1), entao a nota fica presa em 0..100 sem clamp e continua monotona
    — mais variacao ou mais eventos so' consegue baixar. A soma ponderada anterior
    misturava tres numeros que mediam quase a mesma coisa e ainda somava contagem
    absoluta de engasgos, que crescia com a janela.
    """
    if n < SMOOTH_MIN_FRAMES or not m.ft_med or m.ft_jitter is None:
        return None
    excess = max(0.0, m.ft_jitter - SMOOTH_FLOOR_MS)
    steady = math.exp(-SMOOTH_K * (excess / m.ft_med))
    # Solavanco entra pelo tamanho e pelo ritmo: "quantas medianas de atraso por
    # segundo". Exponencial de novo, para nao existir limiar onde um milimetro a
    # mais derrube a nota de um penhasco — e para pico maior nunca pontuar
    # melhor que pico menor, que era o que acontecia com a contagem.
    taxa = (m.jump_severity / m.duration) if m.duration > 0 else 0.0
    penalty = min(SMOOTH_PENALTY_MAX, 1.0 - math.exp(-SMOOTH_EVENT_W * taxa))
    return round(max(0.0, min(100.0, 100.0 * steady * (1.0 - penalty))), 1)


def _classify_bottleneck(m: FrameMetrics, samples: list[tuple]) -> None:
    """Vereditos de gargalo por votacao de quadros, no criterio do PresentMon.

    Cada quadro traz CPUBusy e GPUBusy medidos no mesmo quadro; quem terminou por
    ultimo mandou nele. Contar quadros em vez de comparar medias resolve tres
    problemas de uma vez: nao inventa relacao entre colunas que vieram de quadros
    diferentes (cada uma pode faltar em quadros distintos), da' um veredito estavel
    porque proporcao sobre milhares de quadros quase nao anda entre tiques, e
    permite dizer "empatado" quando e' isso que os dados mostram.
    """
    if m.ft_avg and m.ft_avg > 0:
        # Ocupacao media continua exposta na interface: e' o "quanto do quadro cada
        # motor passou trabalhando", util mesmo quando o veredito e' empate.
        if m.cpu_busy is not None:
            m.cpu_load_ratio = round(min(1.5, m.cpu_busy / m.ft_avg), 3)
        if m.gpu_busy is not None:
            m.gpu_load_ratio = round(min(1.5, m.gpu_busy / m.ft_avg), 3)

    cpu_frames = gpu_frames = capped = paired = 0
    for s in samples:
        cpu, gpu, ft = s[CPU_BUSY], s[GPU_BUSY], s[FT]
        if cpu != cpu or gpu != gpu or ft != ft or ft <= 0:
            continue                     # quadro sem os dois lados nao vota
        paired += 1
        busy = cpu if cpu > gpu else gpu
        if busy < ft * BOTTLENECK_SLACK:
            capped += 1
        elif gpu > cpu * (1.0 + BOTTLENECK_MARGIN):
            gpu_frames += 1
        elif cpu > gpu * (1.0 + BOTTLENECK_MARGIN):
            cpu_frames += 1

    if paired == 0:
        # v1 do PresentMon nao traz CPUBusy/GPUBusy. Melhor admitir do que deduzir
        # gargalo de colunas que ninguem preencheu.
        if m.frames:
            m.bottleneck = BOTTLENECK_NA
            m.bottleneck_detail = "captura sem CPUBusy/GPUBusy (PresentMon v1)"
        return
    if paired < BOTTLENECK_MIN_FRAMES:
        m.bottleneck = BOTTLENECK_NONE
        m.bottleneck_detail = f"coletando ({paired}/{BOTTLENECK_MIN_FRAMES} quadros)"
        return

    m.cpu_bound_pct = round(100.0 * cpu_frames / paired, 1)
    m.gpu_bound_pct = round(100.0 * gpu_frames / paired, 1)
    m.capped_pct = round(100.0 * capped / paired, 1)
    lead = BOTTLENECK_LEAD * 100.0
    if m.capped_pct >= lead:
        m.bottleneck = BOTTLENECK_CAP
        m.bottleneck_detail = (f"nenhum motor saturado em {m.capped_pct:.0f}% "
                               "dos quadros — VSync ou limite de fps")
    elif m.gpu_bound_pct >= lead:
        m.bottleneck = BOTTLENECK_GPU
        m.bottleneck_detail = f"GPU terminou por último em {m.gpu_bound_pct:.0f}% dos quadros"
    elif m.cpu_bound_pct >= lead:
        m.bottleneck = BOTTLENECK_CPU
        m.bottleneck_detail = f"CPU terminou por último em {m.cpu_bound_pct:.0f}% dos quadros"
    else:
        m.bottleneck = BOTTLENECK_BALANCED
        # Empate tecnico e' o caso em que ninguem "ganha" o quadro, e ai' as duas
        # porcentagens ficam perto de zero. Mostrar "CPU 0% · GPU 0%" com as duas
        # pecas a 90% do quadro parecia maquina ociosa, que e' o oposto do que
        # esta' acontecendo — dai' a frase propria.
        empate = 100.0 - m.cpu_bound_pct - m.gpu_bound_pct - m.capped_pct
        if empate >= lead:
            m.bottleneck_detail = (f"CPU e GPU terminam juntas em {empate:.0f}% dos "
                                   "quadros — os dois lados estão no limite")
            return
        m.bottleneck_detail = (f"CPU {m.cpu_bound_pct:.0f}% · GPU {m.gpu_bound_pct:.0f}% "
                               "dos quadros — nenhum lado domina")


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
    # A faixa de "excelente" comeca em 90 porque a nota nova nao gasta pontos com
    # queda de fps: o que sobra abaixo disso ja' e' trepidacao ou travada de verdade.
    if m.smoothness >= 90:
        return "Excelente — cadência regular, praticamente sem engasgos."
    if m.smoothness >= 70:
        return "Bom — pequenas variações, imperceptíveis na maior parte do tempo."
    if m.smoothness >= 50:
        return "Irregular — o intervalo entre quadros oscila o bastante pra sentir."
    return "Ruim — stutter frequente. Vale investigar limites de energia, VRAM ou CPU."

# ── partida inteira ───────────────────────────────────────────────────────────
SESSION_BIN_MS = 0.1
"""Largura do balde do histograma. Define a precisao dos percentis."""
SESSION_MAX_MS = 250.0
"""Acima disso o frame vai para o balde de estouro: e' travada, nao cadencia."""


class SessionRecorder:
    """Estatistica de uma partida inteira, em memoria constante.

    Guardar frame a frame nao serve aqui. Uma sessao de tres horas a 144 fps
    passa de um milhao e meio de amostras, cada uma com oito numeros — centenas
    de megabytes presos no processo enquanto o jogo roda, que e' justamente
    quando a maquina precisa da memoria. Entao nada de lista: cada frame entra
    num histograma de baldes fixos e em quatro acumuladores.

    O custo por frame e' uma divisao, um indice e tres comparacoes, e o tamanho
    nao cresce com a duracao — 2500 inteiros do primeiro ao ultimo minuto. Em
    troca, os percentis saem com a precisao do balde (0,1 ms), o que num frame
    de 7 ms da' menos de 1,5% de erro.
    """

    __slots__ = ("count", "total_ms", "min_ms", "max_ms", "bins", "over",
                 "hitches", "stutters", "_prev_ms", "started_at", "ended_at")

    def __init__(self) -> None:
        self.count = 0
        self.total_ms = 0.0
        self.min_ms = 0.0
        self.max_ms = 0.0
        self.bins = [0] * (int(SESSION_MAX_MS / SESSION_BIN_MS) + 1)
        self.over = 0
        self.hitches = 0
        self.stutters = 0
        self._prev_ms = 0.0
        self.started_at = 0.0
        self.ended_at = 0.0

    def add(self, ft_ms: float) -> None:
        if ft_ms <= 0.0 or ft_ms != ft_ms:      # descarta zero, negativo e NaN
            return
        self.count += 1
        self.total_ms += ft_ms
        if self.min_ms == 0.0 or ft_ms < self.min_ms:
            self.min_ms = ft_ms
        if ft_ms > self.max_ms:
            self.max_ms = ft_ms
        if ft_ms >= SESSION_MAX_MS:
            self.over += 1
        else:
            self.bins[int(ft_ms / SESSION_BIN_MS)] += 1
        if ft_ms >= HITCH_MS:
            self.hitches += 1
        # Engasgo e' frame muito mais lento que o anterior: e' o que se sente
        # como solavanco, mesmo quando a media continua boa.
        if self._prev_ms and ft_ms > self._prev_ms * STUTTER_FACTOR:
            self.stutters += 1
        self._prev_ms = ft_ms

    def worst_avg(self, fraction: float) -> float:
        """Media dos piores `fraction` frames, lida do histograma.

        Percorre os baldes do mais lento para o mais rapido acumulando ate'
        fechar a fatia, usando o meio do balde como valor. O balde de estouro
        entra com o pior frame visto, que e' o unico numero exato que sobrou
        dele.
        """
        if self.count <= 0:
            return 0.0
        alvo = max(1, int(self.count * fraction))
        faltam, soma = alvo, 0.0
        if self.over:
            usar = min(self.over, faltam)
            soma += usar * self.max_ms
            faltam -= usar
        i = len(self.bins) - 1
        while faltam > 0 and i >= 0:
            n = self.bins[i]
            if n:
                usar = min(n, faltam)
                soma += usar * ((i + 0.5) * SESSION_BIN_MS)
                faltam -= usar
            i -= 1
        usados = alvo - faltam
        return (soma / usados) if usados else 0.0

    def result(self) -> dict:
        """Resumo pronto para a interface e para o disco."""
        if self.count <= 0:
            return {"frames": 0}
        medio = self.total_ms / self.count
        pior_1 = self.worst_avg(0.01)
        return {
            "frames": self.count,
            "duracao_s": round(self.ended_at - self.started_at, 1)
                         if self.ended_at else 0.0,
            "fps_avg": round(1000.0 / medio, 1),
            "fps_max": round(1000.0 / self.min_ms, 1) if self.min_ms else 0.0,
            "fps_min": round(1000.0 / self.max_ms, 1) if self.max_ms else 0.0,
            "low_1": round(1000.0 / pior_1, 1) if pior_1 else 0.0,
            "ft_avg": round(medio, 2),
            "ft_max": round(self.max_ms, 2),
            "hitches": self.hitches,
            "stutters": self.stutters,
            "stutter_pct": round(100.0 * self.stutters / self.count, 2),
            "hist": self.compact_hist(),
        }

    def compact_hist(self, alvo: int = 96) -> dict:
        """O histograma reduzido a poucas barras, para caber no disco.

        Os 2500 baldes de 0,1 ms existem para o percentil sair preciso; para
        DESENHAR a distribuicao eles sao caros e inuteis — viraria um arquivo de
        sessoes dezenas de vezes maior para um grafico que tem uns duzentos
        pixels de largura.

        Sem isto a partida guardava so' numeros, e escolher uma sessao na lista
        deixava os graficos exibindo a corrida cronometrada anterior — parecia
        que a tela tinha travado.

        Devolve {"w": largura do balde em ms, "i0": indice do primeiro,
        "c": contagens}. Vazio quando nao ha' frame nenhum.
        """
        if self.count <= 0:
            return {}
        ocupados = [i for i, n in enumerate(self.bins) if n]
        if not ocupados:
            return {}
        # So' a faixa que tem frame de verdade: um jogo a 144 fps vive perto dos
        # 7 ms, e guardar os 243 ms vazios acima disso nao diz nada.
        inicio, fim = ocupados[0], ocupados[-1]
        largura = fim - inicio + 1
        juntar = max(1, -(-largura // alvo))       # divisao para cima
        contagens = []
        for i in range(inicio, fim + 1, juntar):
            contagens.append(sum(self.bins[i:i + juntar]))
        return {"w": round(SESSION_BIN_MS * juntar, 4),
                "i0": inicio, "c": contagens,
                # O balde de estouro entra separado: sao os piores frames da
                # partida, e some-los ao ultimo balde mentiria sobre onde eles
                # estao.
                "over": self.over}
