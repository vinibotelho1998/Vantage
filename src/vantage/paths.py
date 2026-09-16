"""Resolucao de caminhos para execucao do fonte e do PyInstaller."""
from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "Vantage"


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def base_dir() -> Path:
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parents[2]


SANDBOX_ENV = "VANTAGE_DATA_DIR"
"""Aponta os dados para outra pasta. Testes e scripts de screenshot usam isso.

Sem essa valvula, qualquer script que instancie a UI acaba gravando por cima do
settings.json de verdade; foi assim que uma rodada de preview apagou os atalhos
de jogo do usuario. Dado de producao nao pode estar a um import de distancia.
"""


def data_dir() -> Path:
    override = os.environ.get(SANDBOX_ENV)
    base = override or os.environ.get("APPDATA") or os.path.expanduser("~")
    d = Path(base) if override else Path(base) / APP_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def logs_dir() -> Path:
    d = data_dir() / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def log_file() -> Path:
    return logs_dir() / "vantage.log"


def config_file() -> Path:
    return data_dir() / "settings.json"


def legacy_config_file() -> Path:
    return base_dir() / "settings.json"


def vendor_dir(name: str) -> Path:
    root = base_dir()
    for cand in (root / "vendor" / name, root / name):
        if cand.exists():
            return cand
    return root / "vendor" / name


def lhm_dir() -> Path:
    return vendor_dir("lhm")


def packaged_tools_dir() -> Path:
    return base_dir() / "tools"


def writable_tools_dir() -> Path:
    d = data_dir() / "tools"
    d.mkdir(parents=True, exist_ok=True)
    return d


def presentmon_path() -> Path:
    packaged = packaged_tools_dir() / "presentmon.exe"
    if packaged.exists():
        return packaged
    return writable_tools_dir() / "presentmon.exe"


def asset(*parts: str) -> Path:
    return base_dir().joinpath("assets", *parts)
