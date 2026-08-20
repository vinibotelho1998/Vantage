"""Configuracao tipada, validada e persistida em %APPDATA%/DBX Stats/settings.json."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from . import log, paths

_log = log.get("config")

UPDATE_INTERVALS = (0.25, 0.5, 1.0, 2.0)
HISTORY_WINDOWS = (30, 60, 120, 300, 600)
FPS_WINDOWS = (10.0, 30.0, 60.0, 180.0, 300.0)
FPS_NOW_WINDOWS = (0.5, 1.0, 2.0)
ACCENTS = ("cyan", "blue", "green", "purple", "orange", "red", "pink")
CORNERS = ("top-left", "top-right", "bottom-left", "bottom-right")
VIEWS = ("dashboard", "cpu", "gpu", "memory", "network", "sensors",
         "processes", "benchmark", "launcher", "displays", "gamepad")

GAMEPAD_BUTTONS = ("a", "b", "x", "y", "lb", "rb", "back", "start")

OVERLAY_METRICS = [
    ("fps", "FPS"), ("graph", "Gráfico de FPS"), ("low1", "1% Low"),
    ("frametime", "Frametime"), ("cpu", "CPU (uso/temp)"),
    ("gpu", "GPU (uso/temp)"), ("ram", "RAM"), ("vram", "VRAM"),
    ("ping", "Ping"), ("watts", "Consumo"), ("clock", "Relógio"),
]
_OVERLAY_KEYS = {k for k, _ in OVERLAY_METRICS}

DASH_CARDS = [
    ("timeline", "Linha do tempo"), ("fps", "Jogo em foco"),
    ("frametime", "Frametime no card de jogo"), ("cpu", "CPU"), ("gpu", "GPU"),
    ("ram", "Memória"), ("disk", "Armazenamento"), ("net", "Rede"),
]
_DASH_KEYS = {k for k, _ in DASH_CARDS}

DISKBENCH_PHASES = [
    ("wseq", "Escrita seq."), ("rseq", "Leitura seq."),
    ("ralea", "Leitura 4K"), ("walea", "Escrita 4K"),
]
"""Fases do teste de disco. As chaves espelham sensors/diskbench.CHAVES_FASES."""
_DISKBENCH_KEYS = {k for k, _ in DISKBENCH_PHASES}


@dataclass
class Settings:
    # janela
    win_x: int = -1
    win_y: int = -1
    win_w: int = 1360
    win_h: int = 860
    win_maximized: bool = False
    start_maximized: bool = True
    """Abre maximizado. Em janela pequena os cards se apertam e ficam ilegiveis."""
    ui_scale: float = 1.0
    accent: str = "cyan"
    start_view: str = "dashboard"
    always_on_top: bool = False
    start_minimized: bool = False
    close_to_tray: bool = True
    autostart: bool = False

    # coleta
    update_interval: float = 0.5
    history_window: int = 120
    ping_host: str = "8.8.8.8"
    ping_port: int = 53

    # fps
    fps_window: float = 60.0
    fps_now_window: float = 1.0
    fps_pin: str = ""
    fps_auto: bool = True
    fps_only_fullscreen: bool = False

    # graficos
    smooth_lines: bool = True
    show_grid: bool = True
    fill_area: bool = True
    chart_glow: bool = True

    # overlay
    overlay_enabled: bool = True
    overlay_corner: str = "top-left"
    overlay_opacity: float = 0.88
    overlay_scale: float = 1.0
    overlay_metrics: list[str] = field(
        default_factory=lambda: [k for k, _ in OVERLAY_METRICS])
    """Vem completo de proposito: overlay pela metade nao serve para diagnosticar nada."""
    overlay_auto_game: bool = True
    overlay_refresh_hz: float = 3.0
    """Quantas vezes por segundo os numeros trocam. Alto demais nao da' para ler."""
    overlay_graph_seconds: int = 45
    """Janela do grafico de FPS. Menos segundos = tracado mais aberto e mais liso."""
    overlay_columns: int = 0
    """0 decide sozinho pelo numero de metricas; 1 ou 2 forcam o formato."""

    # alertas
    alert_cpu_temp: int = 90
    alert_gpu_temp: int = 85
    alert_ram_pct: int = 0
    alert_vram_pct: int = 0
    alerts_enabled: bool = True

    # painel
    dash_cards: list[str] = field(default_factory=lambda: [k for k, _ in DASH_CARDS])

    # benchmark
    bench_seconds: int = 60
    bench_autosave: bool = True

    # teste de disco
    diskbench_drive: str = ""
    """Unidade da ultima corrida. Vazio = a primeira que o coletor listar."""
    diskbench_size_mib: int = 1024
    """Tamanho do arquivo de teste. Manda tambem na checagem de espaco livre."""
    diskbench_phases: list[str] = field(
        default_factory=lambda: [k for k, _ in DISKBENCH_PHASES])
    diskbench_seconds: float = 1.5
    """Tempo minimo de medicao por fase."""
    diskbench_queue_depth: int = 1
    """Sempre 1: o motor usa I/O sincrono, e fila maior precisaria de OVERLAPPED.

    O campo existe para o dia em que isso mudar — e para deixar registrado que o
    QD1 e' uma limitacao assumida, nao um esquecimento.
    """

    # telas
    display_profiles: list[dict] = field(default_factory=list)
    """Cada perfil e' {"name", "hotkey", "entries": [...]}. Ver platform/displays.py."""
    display_confirm_seconds: int = 15
    """Segundos para desfazer sozinho se a tela nova nao der imagem. 0 desliga."""
    display_restore_on_exit: bool = True
    """Ao fechar, devolve as telas ao arranjo normal."""
    display_restore_after_game: bool = True
    """Quando um jogo fecha, devolve as telas ao perfil padrao — abriu por onde abriu."""
    dashboard_plots: list = field(default_factory=lambda: ["cpu", "gpu", "ram", "vram"])
    """Linhas ligadas no grafico do painel.

    Guardado porque escolher o que olhar e' trabalho, e refazer a cada abertura
    e' o tipo de atrito que faz a pessoa parar de usar o filtro.
    """
    display_default_profile: str = ""
    display_off_by_default: list = field(default_factory=list)
    """monitor_id das telas que devem nascer apagadas.

    A TV da sala fica nesse grupo: conectada e reconhecida, mas fora da area de
    trabalho ate' um atalho de jogo pedir por ela.
    """
    display_primary_default: str = ""
    """monitor_id que deve mandar quando nao ha' jogo pedindo outra coisa.

    E' o "minha tela principal e' essa" da casa: conectar a TV, fechar um jogo
    ou reiniciar o app nao pode mudar quem manda.
    """
    """Perfil que representa o 'meu normal'. Vazio = usa o estado de quando abriu.

    E' para onde as telas voltam depois do jogo e ao fechar o app. Um perfil
    escolhido a dedo e' mais confiavel que uma fotografia tirada num momento
    qualquer, que pode ter pego a maquina ja' fora do arranjo de sempre.
    """

    # atalhos de jogo
    launch_items: list[dict] = field(default_factory=list)
    """Cada item e' {"name", "path", "args", "target", "restore"}. Ver ui/views/launcher.py."""

    # controle como mouse
    gamepad_enabled: bool = True
    """Obsoleto: a escuta e' sempre ligada. Mantido para nao invalidar settings antigos."""
    gamepad_speed: float = 1.0
    gamepad_deadzone: int = 8000
    gamepad_scroll_speed: float = 1.0
    gamepad_toggle_combo: bool = True
    gamepad_bindings: dict = field(default_factory=dict)
    """Botao -> acao, so' o que o usuario mudou; o resto segue o padrao."""
    """Back mais Start liga e desliga o modo mouse sem sair do sofa."""
    gamepad_only_with_tv: bool = False
    """So assume o mouse quando um perfil de tela marcado como sofa estiver ativo."""

    # ── validacao ────────────────────────────────────────────────────────────
    @classmethod
    def _known(cls) -> set[str]:
        return {f.name for f in fields(cls)}

    @classmethod
    def from_dict(cls, data: dict) -> Settings:
        clean = {k: v for k, v in (data or {}).items() if k in cls._known()}
        obj = cls(**clean)
        obj.sanitize()
        return obj

    def as_dict(self) -> dict:
        return asdict(self)

    def sanitize(self) -> None:
        self.win_w = int(_clamp(_num(self.win_w, 1360), 900, 6000))
        self.win_h = int(_clamp(_num(self.win_h, 860), 560, 4000))
        self.ui_scale = round(_clamp(_num(self.ui_scale, 1.0), 0.8, 1.8), 2)
        self.update_interval = _nearest(_num(self.update_interval, 0.5), UPDATE_INTERVALS)
        self.history_window = int(_nearest(_num(self.history_window, 120), HISTORY_WINDOWS))
        self.fps_window = _nearest(_num(self.fps_window, 60.0), FPS_WINDOWS)
        self.fps_now_window = _nearest(_num(self.fps_now_window, 1.0), FPS_NOW_WINDOWS)
        self.overlay_opacity = round(_clamp(_num(self.overlay_opacity, 0.88), 0.3, 1.0), 2)
        self.overlay_scale = round(_clamp(_num(self.overlay_scale, 1.0), 0.7, 2.5), 2)
        self.overlay_refresh_hz = round(_clamp(_num(self.overlay_refresh_hz, 3.0), 1.0, 10.0), 1)
        self.overlay_graph_seconds = int(_clamp(_num(self.overlay_graph_seconds, 45), 10, 300))
        self.overlay_columns = int(_clamp(_num(self.overlay_columns, 0), 0, 2))
        self.ping_port = int(_clamp(_num(self.ping_port, 53), 1, 65535))
        self.bench_seconds = int(_clamp(_num(self.bench_seconds, 60), 10, 3600))

        for key in ("alert_cpu_temp", "alert_gpu_temp"):
            setattr(self, key, int(_clamp(_num(getattr(self, key), 0), 0, 120)))
        for key in ("alert_ram_pct", "alert_vram_pct"):
            setattr(self, key, int(_clamp(_num(getattr(self, key), 0), 0, 100)))

        if self.accent not in ACCENTS:
            self.accent = "cyan"
        if self.start_view not in VIEWS:
            self.start_view = "dashboard"
        if self.overlay_corner not in CORNERS:
            self.overlay_corner = "top-left"
        if not isinstance(self.ping_host, str) or not self.ping_host.strip():
            self.ping_host = "8.8.8.8"
        self.ping_host = self.ping_host.strip()

        self.overlay_metrics = [m for m in _as_list(self.overlay_metrics)
                                if m in _OVERLAY_KEYS] or ["fps", "frametime"]
        self.dash_cards = [c for c in _as_list(self.dash_cards)
                           if c in _DASH_KEYS] or [k for k, _ in DASH_CARDS]

        self._sanitize_diskbench()

        self.display_confirm_seconds = int(_clamp(_num(self.display_confirm_seconds, 15), 0, 60))
        self.launch_items = [i for i in
                             (_clean_launch_item(i) for i in _as_list(self.launch_items))
                             if i]
        self.display_profiles = [p for p in
                                 (_clean_profile(p) for p in _as_list(self.display_profiles))
                                 if p]
        nomes = {p["name"] for p in self.display_profiles}
        if str(self.display_default_profile) not in nomes:
            self.display_default_profile = ""

        self.gamepad_speed = round(_clamp(_num(self.gamepad_speed, 1.0), 0.2, 4.0), 2)
        self.gamepad_scroll_speed = round(_clamp(_num(self.gamepad_scroll_speed, 1.0), 0.2, 4.0), 2)
        self.gamepad_deadzone = int(_clamp(_num(self.gamepad_deadzone, 8000), 0, 30000))
        self.gamepad_bindings = _clean_bindings(self.gamepad_bindings)
        self.display_off_by_default = [str(x) for x in _as_list(self.display_off_by_default)
                                       if str(x)]
        conhecidas = {"cpu", "gpu", "ram", "vram"}
        plots = [str(x) for x in _as_list(self.dashboard_plots) if str(x) in conhecidas]
        # Lista vazia deixaria o grafico em branco sem explicacao nenhuma; nesse
        # caso e' mais provavel arquivo estragado do que escolha deliberada.
        self.dashboard_plots = plots or sorted(conhecidas)

    def _sanitize_diskbench(self) -> None:
        """Opcoes do teste de disco: valor estragado vira padrao, nunca lixo.

        Este e' o unico bloco de configuracao que manda o app escrever gigabytes
        na unidade do usuario. Um settings.json editado a mao com 999999 MiB nao
        pode virar um pedido de 1 TB de arquivo temporario — o teto aqui e' a
        primeira barreira, e a checagem de espaco livre do motor e' a segunda.
        """
        from .sensors.diskbench import PROFUNDIDADES, SEGUNDOS_POR_FASE, TAMANHOS_MIB
        self.diskbench_size_mib = int(_nearest(_num(self.diskbench_size_mib, 1024),
                                               TAMANHOS_MIB))
        self.diskbench_seconds = float(_nearest(_num(self.diskbench_seconds, 1.5),
                                                SEGUNDOS_POR_FASE))
        if self.diskbench_queue_depth not in PROFUNDIDADES:
            self.diskbench_queue_depth = PROFUNDIDADES[0]
        # Ordem canonica, e nao a que veio do arquivo: ler antes de escrever
        # mediria um arquivo vazio. Lista vazia vira o teste completo.
        marcadas = {str(f) for f in _as_list(self.diskbench_phases)}
        self.diskbench_phases = [k for k, _ in DISKBENCH_PHASES
                                 if k in marcadas] or [k for k, _ in DISKBENCH_PHASES]
        self.diskbench_drive = str(self.diskbench_drive or "").strip()[:8]

    # ── persistencia ─────────────────────────────────────────────────────────
    @classmethod
    def load(cls) -> Settings:
        path = paths.config_file()
        if path.exists():
            try:
                return cls.from_dict(json.loads(path.read_text(encoding="utf-8")))
            except Exception as e:
                _log.warning("settings invalido (%s), usando padroes", e)
        legacy = paths.legacy_config_file()
        if legacy.exists():
            try:
                obj = cls.from_dict(json.loads(legacy.read_text(encoding="utf-8")))
                obj.save()
                return obj
            except Exception:
                pass
        return cls()

    def save(self) -> None:
        try:
            path = paths.config_file()
            tmp = path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(self.as_dict(), indent=2, ensure_ascii=False),
                           encoding="utf-8")
            tmp.replace(path)
        except Exception as e:
            _log.warning("falha salvando settings: %s", e)


def _num(v, default: float) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _nearest(v: float, options) -> float:
    return min(options, key=lambda o: abs(o - v))


def _as_list(v) -> list:
    return list(v) if isinstance(v, (list, tuple)) else []


def _prioridade_valida(bruto) -> str:
    """So' aceita chave de prioridade que existe de verdade.

    Um settings.json de outra versao nao pode fazer o app tentar promover um
    jogo para uma classe inexistente na hora de abrir.
    """
    from .sensors.procs import prioridade_por_chave
    chave = str(bruto or "").strip()
    return chave if prioridade_por_chave(chave) else ""


def _clean_launch_item(raw) -> dict | None:
    """Valida um atalho de jogo vindo do disco.

    `target` diz o que fazer com as telas antes de abrir: vazio nao mexe,
    `primary:<monitor_id>` troca a primaria, `profile:<nome>` aplica um perfil.
    """
    if not isinstance(raw, dict):
        return None
    path = str(raw.get("path", "")).strip()
    if not path:
        return None
    target = str(raw.get("target", "")).strip()
    if target and not target.startswith(("primary:", "profile:")):
        target = ""
    name = str(raw.get("name", "")).strip() or Path(path).stem
    return {
        "name": name[:40],
        "path": path,
        "args": str(raw.get("args", "")),
        "target": target,
        "priority": _prioridade_valida(raw.get("priority", "")),
        # Ligado por padrao: gravar a partida custa uma soma por quadro e 20 KB
        # fixos, e o resumo no fim e' justamente o que o atalho existe para dar.
        "bench": bool(raw.get("bench", True)),
        "restore": bool(raw.get("restore", True)),
    }


def _clean_bindings(raw) -> dict:
    """Guarda so' botao e acao que existem de verdade.

    Um settings.json de versao antiga (ou editado a mao) nao pode fazer o modo
    mouse subir com botao apontando para acao inexistente.
    """
    from .platform.gamepad import ACTIONS, DEFAULT_BINDINGS
    if not isinstance(raw, dict):
        return {}
    return {str(k): str(v) for k, v in raw.items()
            if str(k) in DEFAULT_BINDINGS and str(v) in ACTIONS}


def _clean_profile(raw) -> dict | None:
    """Valida um perfil de telas vindo do disco.

    Perfil sem nenhuma tela ligada e' descartado: aplicar isso deixaria a maquina
    sem imagem nenhuma e sem como voltar.
    """
    if not isinstance(raw, dict):
        return None
    name = str(raw.get("name", "")).strip()
    if not name:
        return None
    entries = []
    for item in _as_list(raw.get("entries")):
        if not isinstance(item, dict) or not item.get("device"):
            continue
        mode = item.get("mode")
        if isinstance(mode, (list, tuple)) and len(mode) == 3:
            try:
                mode = [int(mode[0]), int(mode[1]), int(mode[2])]
            except (TypeError, ValueError):
                mode = None
        else:
            mode = None
        pos = item.get("position")
        if isinstance(pos, (list, tuple)) and len(pos) == 2:
            try:
                pos = [int(pos[0]), int(pos[1])]
            except (TypeError, ValueError):
                pos = [0, 0]
        else:
            pos = [0, 0]
        entries.append({
            "device": str(item.get("device")),
            "monitor_id": str(item.get("monitor_id", "")),
            "name": str(item.get("name", "")),
            "active": bool(item.get("active")),
            "primary": bool(item.get("primary")),
            "position": pos,
            "mode": mode,
        })
    if not any(e["active"] for e in entries):
        return None
    topology = str(raw.get("topology", "")).strip().lower()
    if topology not in ("", "clone"):
        topology = ""
    return {"name": name[:40], "hotkey": str(raw.get("hotkey", "")),
            "topology": topology, "entries": entries}

