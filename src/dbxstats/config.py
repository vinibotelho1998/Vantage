"""Configuracao tipada com persistencia em %APPDATA% e migracao do formato antigo."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields

from . import log, paths

_log = log.get("config")

_INTERVALS = (0.25, 0.5, 1.0, 2.0)
_FPS_WINDOWS = (0.25, 0.5, 1.0)
_POSITIONS = {"right", "left", "bottom-right", "bottom-left", "top-right", "top-left"}
_FPS_SOURCES = {"present", "display"}
_ACCENTS = {"blue", "green", "purple", "orange", "red", "cyan"}
_ALL_FPS_METRICS = ["inst", "avg", "1low", "01low", "frametime", "graph"]
_ALL_STATS_KEYS = ["cpu_pct", "cpu_temp", "cpu_watts", "gpu_pct", "gpu_temp",
                   "gpu_watts", "ram_pct", "fps", "ping_ms", "nvme_temp"]


@dataclass
class Settings:
    position: str = "bottom-right"
    opacity: float = 0.95
    always_on_top: bool = True
    update_interval: float = 1.0
    autostart: bool = False
    width: int = 250
    hide_fullscreen: bool = False
    fps_window: float = 0.5
    fps_source: str = "present"
    fps_pin: str = ""
    fps_metrics: list[str] = field(default_factory=lambda: list(_ALL_FPS_METRICS))
    show_stats: bool = False
    locked: bool = False
    stats_keys: list[str] = field(
        default_factory=lambda: ["cpu_pct", "cpu_temp", "cpu_watts",
                                 "gpu_pct", "gpu_temp", "gpu_watts",
                                 "fps", "ping_ms"])
    ping_host: str = "8.8.8.8"
    ping_port: int = 53
    accent: str = "blue"
    overlay_corner: str = "top-left"

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
        self.opacity = _clamp(_as_float(self.opacity, 0.95), 0.4, 1.0)
        self.update_interval = _nearest(_as_float(self.update_interval, 1.0), _INTERVALS)
        self.fps_window = _nearest(_as_float(self.fps_window, 0.5), _FPS_WINDOWS)
        self.width = int(_clamp(_as_float(self.width, 250), 180, 600))
        if self.position not in _POSITIONS:
            self.position = "bottom-right"
        if self.fps_source not in _FPS_SOURCES:
            self.fps_source = "present"
        self.fps_metrics = [m for m in self.fps_metrics if m in _ALL_FPS_METRICS] or list(_ALL_FPS_METRICS)
        self.stats_keys = [k for k in self.stats_keys if k in _ALL_STATS_KEYS]
        self.ping_port = int(_clamp(_as_float(self.ping_port, 53), 1, 65535))
        if not isinstance(self.ping_host, str) or not self.ping_host.strip():
            self.ping_host = "8.8.8.8"
        if self.accent not in _ACCENTS:
            self.accent = "blue"
        if self.overlay_corner not in {"top-left", "top-right", "bottom-left", "bottom-right"}:
            self.overlay_corner = "top-left"

    @classmethod
    def load(cls) -> Settings:
        path = paths.config_file()
        if not path.exists():
            legacy = paths.legacy_config_file()
            if legacy.exists() and legacy != path:
                try:
                    obj = cls.from_dict(json.loads(legacy.read_text(encoding="utf-8")))
                    obj.save()
                    _log.info("settings migrado de %s", legacy)
                    return obj
                except Exception as e:
                    _log.warning("falha migrando settings legado: %s", e)
        if path.exists():
            try:
                return cls.from_dict(json.loads(path.read_text(encoding="utf-8")))
            except Exception as e:
                _log.warning("settings invalido (%s), usando padroes", e)
        return cls()

    def save(self) -> None:
        try:
            paths.config_file().write_text(
                json.dumps(self.as_dict(), indent=2, ensure_ascii=False),
                encoding="utf-8")
        except Exception as e:
            _log.warning("falha salvando settings: %s", e)


def _as_float(v, default: float) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _nearest(v: float, options: tuple[float, ...]) -> float:
    return min(options, key=lambda o: abs(o - v))


ALL_STATS_LABELS = [
    ("cpu_pct", "CPU — Uso (%)"),
    ("cpu_temp", "CPU — Temperatura (°C)"),
    ("cpu_watts", "CPU — Potência (W)"),
    ("gpu_pct", "GPU — Uso (%)"),
    ("gpu_temp", "GPU — Temperatura (°C)"),
    ("gpu_watts", "GPU — Potência (W)"),
    ("ram_pct", "RAM — Uso (%)"),
    ("fps", "FPS"),
    ("ping_ms", "Rede — Ping (ms)"),
    ("nvme_temp", "Disco — Temperatura (°C)"),
]
