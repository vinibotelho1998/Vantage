"""Dados de saída fornecidos pelo compositor através do Qt."""
import os
from dataclasses import dataclass
from pathlib import Path
import sys
import tempfile

from PySide6.QtGui import QGuiApplication

from .. import paths


@dataclass(frozen=True)
class Display:
    name: str
    monitor_id: str
    primary: bool
    active: bool = True


def list_displays(with_modes=True):
    return [Display(screen.name(), screen.name(), screen == QGuiApplication.primaryScreen())
            for screen in QGuiApplication.screens()]


def snapshot():
    return [{"name": d.name, "monitor_id": d.monitor_id, "device": d.name, "active": True,
             "primary": d.primary} for d in list_displays()]


def set_autostart(enable):
    entry = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "autostart/vantage.desktop"
    if not enable:
        entry.unlink(missing_ok=True)
        return
    launcher = paths.base_dir() / "Vantage.sh"
    # Instalações por wheel usam o ponto de entrada Python em vez do shell do fonte.
    argv = [str(launcher)] if launcher.is_file() else [sys.executable, "-m", "vantage"]
    command = " ".join(_exec_arg(arg) for arg in argv)
    entry.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", dir=entry.parent, delete=False, encoding="utf8") as stage:
        tmp = Path(stage.name)
        stage.write(f"[Desktop Entry]\nType=Application\nName=Vantage\nExec={command}\n")
    try:
        tmp.replace(entry)
    finally:
        tmp.unlink(missing_ok=True)


def _exec_arg(value):
    # O campo Exec passa primeiro pelo leitor de strings do .desktop e depois
    # pelo tokenizer de argumentos. A barra de escape precisa sobreviver aos dois.
    quoted = value.replace('\\', '\\\\').replace('"', '\\"').replace('$', '\\$').replace('`', '\\`').replace('%', '%%')
    return '"' + quoted.replace("\\", "\\\\") + '"'
