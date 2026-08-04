"""Configuracao tipada, validada e persistida em %APPDATA%/DBX Stats/settings.json."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields

from . import log, paths

_log = log.get("config")

UPDATE_INTERVALS = (0.25, 0.5, 1.0, 2.0)
HISTORY_WINDOWS = (30, 60, 120, 300, 600)
FPS_WINDOWS = (10.0, 30.0, 60.0, 180.0, 300.0)
FPS_NOW_WINDOWS = (0.5, 1.0, 2.0)
ACCENTS = ("cyan", "blue", "green", "purple", "orange", "red", "pink")
CORNERS = ("top-left", "top-right", "bottom-left", "bottom-right")
VIEWS = ("dashboard", "gaming", "cpu", "gpu", "memory", "network", "sensors",
         "processes", "benchmark")

OVERLAY_METRICS = [
    ("fps", "FPS"), ("low1", "1% Low"), ("low01", "0.1% Low"), ("frametime", "Frametime"),
    ("cpu", "CPU (uso/temp)"), ("gpu", "GPU (uso/temp)"), ("ram", "RAM"),
    ("vram", "VRAM"), ("ping", "Ping"), ("watts", "Consumo"), ("clock", "Relógio"),
]
_OVERLAY_KEYS = {k for k, _ in OVERLAY_METRICS}

DASH_CARDS = [
    ("timeline", "Linha do tempo"), ("fps", "Jogo em foco"),
    ("frametime", "Frametime no card de jogo"), ("cpu", "CPU"), ("gpu", "GPU"),
    ("ram", "Memória"), ("disk", "Armazenamento"), ("net", "Rede"),
]
_DASH_KEYS = {k for k, _ in DASH_CARDS}


@dataclass
class Settings:
    # janela
    win_x: int = -1
    win_y: int = -1
    win_w: int = 1360
    win_h: int = 860
    win_maximized: bool = False
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
    overlay_enabled: bool = False
    overlay_corner: str = "top-left"
    overlay_opacity: float = 0.88
    overlay_scale: float = 1.0
    overlay_metrics: list[str] = field(
        default_factory=lambda: ["fps", "low1", "frametime", "cpu", "gpu", "ram"])
    overlay_auto_game: bool = True

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
