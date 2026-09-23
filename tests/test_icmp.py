"""Ping ICMP sem rede: a iphlpapi e o DNS sao falsos.

O que importa aqui e' a leitura da resposta: status diferente de sucesso tem de
virar "sem resposta", 0 ms nao pode virar "sem resposta", e o handle nao pode
ser aberto de novo a cada ping.
"""
import ctypes

import pytest

from vantage.platform import icmp


class _IphlpapiFalsa:
    def __init__(self, rtt=12, status=0, enviados=1, handle=1234):
        self.rtt = rtt
        self.status = status
        self.enviados = enviados
        self.handle = handle
        self.abertos = 0
        self.fechados = []
        self.destinos = []

    def IcmpCreateFile(self):
        self.abertos += 1
        return self.handle

    def IcmpCloseHandle(self, h):
        self.fechados.append(h)

    def IcmpSendEcho(self, handle, destino, payload, tam, opcoes, buffer, tam_buffer, timeout):
        self.destinos.append(destino)
        resposta = icmp.ICMP_ECHO_REPLY()
        resposta.Status = self.status
        resposta.RoundTripTime = self.rtt
        ctypes.memmove(buffer, ctypes.addressof(resposta), ctypes.sizeof(resposta))
        return self.enviados


@pytest.fixture
def api(monkeypatch):
    falsa = _IphlpapiFalsa()
    monkeypatch.setattr(icmp, "_iphlpapi", falsa)
    monkeypatch.setattr(icmp, "_ready", True)
    monkeypatch.setattr(icmp, "_handle", None)
    monkeypatch.setattr(icmp.socket, "gethostbyname", lambda host: "10.0.0.1")
    return falsa


def test_resposta_devolve_o_rtt_em_ms(api):
    api.rtt = 23
    assert icmp.ping("servidor") == 23.0


def test_destino_vai_na_ordem_de_rede(api):
    icmp.ping("servidor")
    assert api.destinos == [int.from_bytes(bytes([10, 0, 0, 1]), "little")]


def test_zero_ms_nao_vira_sem_resposta(api):
    """A API arredonda para ms inteiro; rede local responde em 0."""
    api.rtt = 0
    assert icmp.ping("roteador") == 0.1


def test_status_de_erro_e_sem_resposta(api):
    api.status = 11010                               # IP_REQ_TIMED_OUT
    assert icmp.ping("servidor") is None


def test_nada_enviado_e_sem_resposta(api):
    api.enviados = 0
    assert icmp.ping("servidor") is None


def test_nome_que_nao_resolve_e_sem_resposta(api, monkeypatch):
    def falha(host):
        raise OSError("getaddrinfo failed")
    monkeypatch.setattr(icmp.socket, "gethostbyname", falha)
    assert icmp.ping("nao.existe") is None
    assert api.destinos == []


def test_handle_e_aberto_uma_vez_so(api):
    for _ in range(5):
        icmp.ping("servidor")
    assert api.abertos == 1


def test_handle_invalido_nao_e_guardado(api):
    api.handle = icmp.INVALID_HANDLE_VALUE
    assert icmp.ping("servidor") is None
    assert icmp._handle is None


def test_fechar_solta_o_handle_e_permite_reabrir(api):
    icmp.ping("servidor")
    icmp.close()
    assert api.fechados == [1234]
    assert icmp._handle is None
    icmp.ping("servidor")
    assert api.abertos == 2


def test_sem_a_dll_nao_tenta_nada(monkeypatch):
    monkeypatch.setattr(icmp, "_ready", False)
    monkeypatch.setattr(icmp, "_handle", None)
    assert icmp.ping("servidor") is None
