"""Excecao que ninguem tratou vai para o log.

No executavel nao ha' console: sem estes ganchos, a falha de um slot ou de uma
thread solta some sem uma linha, e foi assim que a sonda de saude dos discos
parou de vez sem deixar rastro.
"""
import logging
import sys
import threading

import pytest

from vantage import log


class _Coletor(logging.Handler):
    def __init__(self):
        super().__init__()
        self.registros = []

    def emit(self, record):
        self.registros.append(record)


@pytest.fixture
def ganchos(monkeypatch):
    """Ganchos falsos no lugar dos do Python, restaurados pelo monkeypatch."""
    chamados = {"principal": [], "thread": []}
    monkeypatch.setattr(sys, "excepthook", lambda *a: chamados["principal"].append(a))
    monkeypatch.setattr(threading, "excepthook", lambda a: chamados["thread"].append(a))
    coletor = _Coletor()
    logger = logging.getLogger("vantage.falha")
    logger.addHandler(coletor)
    log.capturar_excecoes()
    yield chamados, coletor
    logger.removeHandler(coletor)


def _args_thread(tipo, valor):
    return threading.ExceptHookArgs((tipo, valor, None, threading.current_thread()))


def test_excecao_da_thread_principal_vai_para_o_log_e_segue_adiante(ganchos):
    chamados, coletor = ganchos
    erro = ValueError("quebrou")
    sys.excepthook(ValueError, erro, None)
    assert len(coletor.registros) == 1
    assert coletor.registros[0].exc_info[1] is erro
    assert len(chamados["principal"]) == 1


def test_excecao_de_thread_vai_para_o_log_com_o_nome_da_thread(ganchos):
    chamados, coletor = ganchos
    sys_thread = threading.current_thread().name
    threading.excepthook(_args_thread(RuntimeError, RuntimeError("sonda")))
    assert len(coletor.registros) == 1
    assert sys_thread in coletor.registros[0].getMessage()
    assert len(chamados["thread"]) == 1


def test_thread_encerrada_com_system_exit_nao_e_falha(ganchos):
    _chamados, coletor = ganchos
    threading.excepthook(_args_thread(SystemExit, SystemExit(0)))
    assert coletor.registros == []


def test_sem_console_o_gancho_antigo_nao_e_chamado(ganchos, monkeypatch):
    """Sem stderr, o gancho padrao escreveria num arquivo que nao existe."""
    chamados, coletor = ganchos
    monkeypatch.setattr(sys, "stderr", None)
    sys.excepthook(ValueError, ValueError("x"), None)
    threading.excepthook(_args_thread(ValueError, ValueError("y")))
    assert len(coletor.registros) == 2
    assert chamados == {"principal": [], "thread": []}
