"""Logging central com rotacao em %APPDATA%/Vantage/logs."""
from __future__ import annotations

import logging
import os
import sys
import threading
from logging.handlers import RotatingFileHandler

from . import paths

_configured = False


def setup(level: int = logging.INFO) -> None:
    global _configured
    if _configured:
        return
    _configured = True
    root = logging.getLogger("vantage")
    root.setLevel(level)
    root.propagate = False
    fmt = logging.Formatter("%(asctime)s %(levelname)-5s %(name)s: %(message)s", "%H:%M:%S")
    if os.environ.get("VANTAGE_NO_FILE_LOG"):
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
    return logging.getLogger(f"vantage.{name}")


def capturar_excecoes() -> None:
    """Manda para o log toda excecao que ninguem tratou.

    No executavel empacotado nao ha' console: o PySide6 entrega a excecao de um
    slot ao sys.excepthook, que imprime num stderr que nao existe, e a falha
    some sem rastro. Thread solta morre do mesmo jeito, e foi assim que a sonda
    de saude dos discos parou de vez sem uma linha no log. Os ganchos antigos
    continuam sendo chamados depois: rodando do fonte, o traceback ainda sai no
    terminal.
    """
    falhas = get("falha")
    anterior = sys.excepthook
    anterior_thread = threading.excepthook

    def _principal(tipo, valor, rastro) -> None:
        falhas.error("excecao nao tratada", exc_info=(tipo, valor, rastro))
        if sys.stderr is not None:
            anterior(tipo, valor, rastro)

    def _thread(args) -> None:
        if args.exc_type is not SystemExit:
            nome = getattr(args.thread, "name", "?")
            falhas.error("excecao nao tratada na thread %s", nome,
                         exc_info=(args.exc_type, args.exc_value, args.exc_traceback))
        if sys.stderr is not None:
            anterior_thread(args)

    sys.excepthook = _principal
    threading.excepthook = _thread
