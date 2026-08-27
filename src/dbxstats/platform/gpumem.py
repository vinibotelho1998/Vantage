"""VRAM de um processo, pelo contador de desempenho do Windows.

O total de VRAM ja' aparece no overlay, mas ele nao responde a pergunta que
importa quando a memoria estoura: quanto disso e' o JOGO. O resto pode ser o
compositor da area de trabalho, o navegador aberto atras, o proprio app, e num
placar de 12 GB a diferenca entre "o jogo pegou 11" e "o jogo pegou 6 e o Chrome
levou o resto" muda completamente o que se faz a seguir.

O caminho e' o mesmo do Gerenciador de Tarefas: o contador `GPU Process Memory`,
lido por PDH. Nao existe API simples de "VRAM deste pid" fora disso: o
LibreHardwareMonitor da' o total do adaptador, e a NVML nao serve nesta maquina
(a GPU e' AMD) nem responde por processo.

A instancia do contador tem a forma `pid_1234_luid_0x..._phys_0`, e um mesmo
processo aparece em varias delas: uma por adaptador e segmento. Por isso a
consulta usa curinga e SOMA o que voltar: ler so' a primeira daria um numero
parcial, e num sistema com GPU integrada mais dedicada daria justamente a
errada.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes

from .. import log

_log = log.get("gpumem")

pdh = ctypes.WinDLL("pdh", use_last_error=True)

ERROR_SUCCESS = 0
PDH_FMT_LARGE = 0x00000400
"""Formata como inteiro de 64 bits. O contador e' em bytes e passa de 4 GB."""


class PDH_FMT_COUNTERVALUE_ITEM_W(ctypes.Structure):
    """Item devolvido por PdhGetFormattedCounterArrayW.

    O `_pad` e' explicito de proposito: em 64 bits o `CStatus` de 4 bytes fica
    seguido de 4 de alinhamento antes do valor de 8, e sem ele o ctypes leria o
    numero deslocado, devolvendo lixo em vez de bytes.
    """

    _fields_ = [("szName", wintypes.LPWSTR),
                ("CStatus", wintypes.DWORD),
                ("_pad", ctypes.c_uint32),
                ("largeValue", ctypes.c_longlong)]


def _setup() -> None:
    pdh.PdhOpenQueryW.argtypes = [wintypes.LPCWSTR, ctypes.c_void_p,
                                  ctypes.POINTER(ctypes.c_void_p)]
    pdh.PdhOpenQueryW.restype = ctypes.c_long
    pdh.PdhAddEnglishCounterW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR,
                                          ctypes.c_void_p,
                                          ctypes.POINTER(ctypes.c_void_p)]
    pdh.PdhAddEnglishCounterW.restype = ctypes.c_long
    pdh.PdhCollectQueryData.argtypes = [ctypes.c_void_p]
    pdh.PdhCollectQueryData.restype = ctypes.c_long
    pdh.PdhGetFormattedCounterArrayW.argtypes = [
        ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD),
        ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
    pdh.PdhGetFormattedCounterArrayW.restype = ctypes.c_long
    pdh.PdhCloseQuery.argtypes = [ctypes.c_void_p]
    pdh.PdhCloseQuery.restype = ctypes.c_long


_setup()


class ProcessVram:
    """VRAM dedicada de um processo, com a consulta PDH presa entre os ciclos.

    A consulta fica aberta porque abrir e fechar a cada leitura custa alguns
    milissegundos e o laco roda a 1 Hz o jogo inteiro. Ela so' e' refeita quando
    o pid muda: o curinga do caminho leva o pid dentro, entao nao da' para
    reaproveitar entre jogos.
    """

    # `Local Usage` e' a VRAM dedicada da placa, que e' o numero que estoura e
    # derruba o fps. `Non Local Usage` (memoria do sistema usada como VRAM) fica
    # de fora: ela cresce justamente DEPOIS que a dedicada acabou, e mistura-la
    # ao total esconderia o momento em que o problema comecou.
    CONTADOR = r"\GPU Process Memory(pid_{pid}*)\Local Usage"

    def __init__(self) -> None:
        self._wanted = 0
        """Escrito pela thread da interface, lido pela do coletor: so' um int."""
        self._pid = 0
        self._query = None
        self._counter = None
        self._quebrado = False
        """Contador ausente nesta maquina; nao adianta tentar de novo."""

    def follow(self, pid: int | None) -> None:
        self._wanted = int(pid or 0)

    def close(self) -> None:
        if self._query is not None:
            pdh.PdhCloseQuery(self._query)
        self._query = None
        self._counter = None
        self._pid = 0

    def _abrir(self, pid: int) -> bool:
        self.close()
        query = ctypes.c_void_p()
        if pdh.PdhOpenQueryW(None, None, ctypes.byref(query)) != ERROR_SUCCESS:
            return False
        counter = ctypes.c_void_p()
        caminho = self.CONTADOR.format(pid=pid)
        if pdh.PdhAddEnglishCounterW(query, caminho, None,
                                     ctypes.byref(counter)) != ERROR_SUCCESS:
            pdh.PdhCloseQuery(query)
            # Sem o contador nao ha' o que medir: ou o Windows e' antigo demais,
            # ou o processo nao tocou na GPU ainda. O segundo caso se resolve
            # sozinho na proxima leitura, entao nada de marcar como quebrado.
            return False
        self._query, self._counter, self._pid = query, counter, pid
        return True

    def read_mb(self) -> float | None:
        """VRAM dedicada do processo agora, em MB. None quando nao da' para medir."""
        if self._quebrado:
            return None
        pid = self._wanted
        if not pid:
            self.close()
            return None
        if pid != self._pid and not self._abrir(pid):
            return None

        try:
            if pdh.PdhCollectQueryData(self._query) != ERROR_SUCCESS:
                return None
            tamanho = wintypes.DWORD(0)
            quantos = wintypes.DWORD(0)
            pdh.PdhGetFormattedCounterArrayW(self._counter, PDH_FMT_LARGE,
                                             ctypes.byref(tamanho),
                                             ctypes.byref(quantos), None)
            if tamanho.value == 0:
                # Processo sem nada na GPU: zero e' resposta, e nao ausencia.
                return 0.0
            buf = ctypes.create_string_buffer(tamanho.value)
            if pdh.PdhGetFormattedCounterArrayW(self._counter, PDH_FMT_LARGE,
                                                ctypes.byref(tamanho),
                                                ctypes.byref(quantos),
                                                buf) != ERROR_SUCCESS:
                return None
            itens = ctypes.cast(buf, ctypes.POINTER(PDH_FMT_COUNTERVALUE_ITEM_W))
            total = 0
            for i in range(quantos.value):
                item = itens[i]
                if item.CStatus == ERROR_SUCCESS:
                    total += item.largeValue
            return round(total / 1024 ** 2, 1)
        except OSError as e:                                 # noqa: BLE001
            _log.debug("leitura de VRAM do processo falhou: %s", e)
            return None


def disponivel() -> bool:
    """O contador existe nesta maquina?

    Serve para a interface nao oferecer uma metrica que nunca vai preencher.
    """
    query = ctypes.c_void_p()
    if pdh.PdhOpenQueryW(None, None, ctypes.byref(query)) != ERROR_SUCCESS:
        return False
    try:
        counter = ctypes.c_void_p()
        caminho = r"\GPU Process Memory(*)\Local Usage"
        return pdh.PdhAddEnglishCounterW(query, caminho, None,
                                         ctypes.byref(counter)) == ERROR_SUCCESS
    finally:
        pdh.PdhCloseQuery(query)
