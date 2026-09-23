"""Excecao que ninguem tratou tem de chegar ao log.

No executavel empacotado nao ha' console. O PySide6 entrega a excecao de um
slot ao sys.excepthook, que imprime num stderr que nao existe; thread solta
morre do mesmo jeito. Sem os ganchos, a falha sumia sem rastro nenhum.
"""
import logging
import sys
import threading

from vantage import log


class _Guardar(logging.Handler):
    def __init__(self):
        super().__init__()
        self.registros: list[logging.LogRecord] = []

    def emit(self, record):
        self.registros.append(record)


def _ouvir(monkeypatch) -> _Guardar:
    # Os ganchos originais voltam no fim do teste, instalados ou nao.
    monkeypatch.setattr(sys, "excepthook", sys.excepthook)
    monkeypatch.setattr(threading, "excepthook", threading.excepthook)
    guardar = _Guardar()
    raiz = logging.getLogger("vantage")
    raiz.addHandler(guardar)
    monkeypatch.setattr(raiz, "handlers", raiz.handlers)
    return guardar


def test_excecao_de_thread_solta_vai_para_o_log(monkeypatch):
    guardar = _ouvir(monkeypatch)
    monkeypatch.setattr(sys, "stderr", None)      # como no executavel sem console
    log.capturar_excecoes()

    def _quebra():
        raise ValueError("sonda quebrou")

    t = threading.Thread(target=_quebra, name="diskhealth")
    t.start()
    t.join()

    falhas = [r for r in guardar.registros if r.exc_info]
    assert falhas, "a excecao da thread nao chegou ao log"
    assert falhas[0].exc_info[0] is ValueError
    assert "diskhealth" in falhas[0].getMessage()


def test_excecao_de_slot_vai_para_o_log(monkeypatch):
    guardar = _ouvir(monkeypatch)
    monkeypatch.setattr(sys, "stderr", None)
    log.capturar_excecoes()

    try:
        raise KeyError("chave que o slot esperava")
    except KeyError:
        sys.excepthook(*sys.exc_info())

    falhas = [r for r in guardar.registros if r.exc_info]
    assert falhas and falhas[0].exc_info[0] is KeyError
