"""Logging central com rotacao em %APPDATA%/DBX Stats/logs."""
from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler

from . import paths

_configured = False


def setup(level: int = logging.INFO) -> None:
    global _configured
    if _configured:
        return
    _configured = True
    root = logging.getLogger("dbxstats")
    root.setLevel(level)
    root.propagate = False
    fmt = logging.Formatter("%(asctime)s %(levelname)-5s %(name)s: %(message)s", "%H:%M:%S")
    if os.environ.get("DBXSTATS_NO_FILE_LOG"):
        # Teste e script de desenvolvimento nao sujam o log do app instalado.
        return
    try:
        fh = RotatingFileHandler(paths.log_file(), maxBytes=512_000, backupCount=2, encoding="utf-8")
        fh.setFormatter(fmt)
        root.addHandler(fh)
    except Exception:
        pass
    if not paths.is_frozen():
        sh = logging.StreamHandler()
        sh.setFormatter(fmt)
        root.addHandler(sh)


def get(name: str) -> logging.Logger:
    setup()
    return logging.getLogger(f"dbxstats.{name}")
