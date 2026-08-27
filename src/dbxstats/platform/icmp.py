"""Ping ICMP pelo `IcmpSendEcho` do Windows (iphlpapi).

Servidor de jogo quase sempre fala UDP: abrir TCP na porta dele nao mede nada
util, quando muito devolve "recusado". ICMP e' o que da' latencia e perda de
verdade, e por esta API, sem socket raw e sem privilegio especial.
"""
from __future__ import annotations

import ctypes
import socket
from ctypes import wintypes

from .. import log

_log = log.get("icmp")

try:
    _iphlpapi = ctypes.WinDLL("iphlpapi", use_last_error=True)
except OSError:                                     # pragma: no cover
    _iphlpapi = None

INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value


class IP_OPTION_INFORMATION(ctypes.Structure):
    _fields_ = [("Ttl", ctypes.c_ubyte), ("Tos", ctypes.c_ubyte),
                ("Flags", ctypes.c_ubyte), ("OptionsSize", ctypes.c_ubyte),
                ("OptionsData", ctypes.POINTER(ctypes.c_ubyte))]


class ICMP_ECHO_REPLY(ctypes.Structure):
    _fields_ = [("Address", ctypes.c_uint32), ("Status", ctypes.c_ulong),
                ("RoundTripTime", ctypes.c_ulong), ("DataSize", ctypes.c_ushort),
                ("Reserved", ctypes.c_ushort), ("Data", ctypes.c_void_p),
                ("Options", IP_OPTION_INFORMATION)]


def _setup() -> bool:
    if _iphlpapi is None:
        return False
    _iphlpapi.IcmpCreateFile.restype = wintypes.HANDLE
    _iphlpapi.IcmpCloseHandle.argtypes = [wintypes.HANDLE]
    _iphlpapi.IcmpSendEcho.restype = wintypes.DWORD
    _iphlpapi.IcmpSendEcho.argtypes = [
        wintypes.HANDLE, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_ushort,
        ctypes.POINTER(IP_OPTION_INFORMATION), ctypes.c_void_p,
        wintypes.DWORD, wintypes.DWORD]
    return True


_ready = _setup()
_handle: int | None = None


def available() -> bool:
    return _ready


def _open() -> int | None:
    """Um handle so' para todo o processo; abrir por ping vaza descritor."""
    global _handle
    if not _ready:
        return None
    if _handle is None:
        h = _iphlpapi.IcmpCreateFile()
        if not h or h == INVALID_HANDLE_VALUE:
            return None
        _handle = h
    return _handle


def ping(host: str, timeout_ms: int = 1000) -> float | None:
    """RTT em milissegundos, ou None quando nao volta resposta."""
    handle = _open()
    if handle is None:
        return None
    try:
        endereco = socket.inet_aton(socket.gethostbyname(host))
    except OSError:
        return None
    destino = int.from_bytes(endereco, "little")

    payload = b"dbxstats-ping"
    buffer_size = ctypes.sizeof(ICMP_ECHO_REPLY) + len(payload) + 8
    buffer = ctypes.create_string_buffer(buffer_size)
    enviados = _iphlpapi.IcmpSendEcho(handle, destino, payload, len(payload),
                                      None, buffer, buffer_size, timeout_ms)
    if not enviados:
        return None
    reply = ctypes.cast(buffer, ctypes.POINTER(ICMP_ECHO_REPLY)).contents
    if reply.Status != 0:                            # 0 = IP_SUCCESS
        return None
    # A API arredonda para milissegundo inteiro; 0 vira 0.1 para nao virar "sem
    # resposta" na leitura de quem consome.
    return float(reply.RoundTripTime) or 0.1


def close() -> None:
    global _handle
    if _handle is not None and _ready:
        try:
            _iphlpapi.IcmpCloseHandle(_handle)
        except OSError:
            pass
        _handle = None
