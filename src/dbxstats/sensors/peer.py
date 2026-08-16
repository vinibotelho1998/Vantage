"""Descobre com qual servidor um jogo esta' falando.

O Windows nao guarda o endereco remoto na tabela de UDP — `netstat` e psutil
mostram as portas locais do processo e mais nada. Como jogo online quase sempre
e' UDP, ficar so' na tabela deixa o ping apontado para um DNS publico, que nao
diz nada sobre a partida.

A saida e' cruzar as duas metades da informacao: a porta local sai da tabela por
processo, e o outro lado da conversa sai do trafego. Um socket raw em modo
promiscuo (SIO_RCVALL, exige admin) ve os pacotes; casando pela porta local,
sobra o endereco do servidor.

A varredura e' curta e espacada de proposito: alguns segundos bastam para o par
mais falante aparecer, e o resultado vale por bastante tempo — servidor de
partida nao muda a toda hora.
"""
from __future__ import annotations

import collections
import socket
import struct
import threading
import time

import psutil

from .. import log

_log = log.get("peer")

SNIFF_S = 3.0
"""Tempo farejando. O servidor da partida aparece em menos de um segundo."""
REFRESH_S = 90.0
"""Intervalo entre buscas para o mesmo processo."""
MIN_PACKETS = 8
"""Abaixo disso e' ruido de descoberta, nao a conversa com o servidor."""
_UDP = 17


def available() -> bool:
    return hasattr(socket, "SIO_RCVALL")


def local_ports(pid: int) -> set[int]:
    """Portas UDP que o processo abriu — a metade da informacao que o Windows da'."""
    if pid <= 4:
        return set()
    try:
        conexoes = psutil.Process(pid).net_connections(kind="inet")
    except (psutil.Error, OSError):
        return set()
    return {c.laddr.port for c in conexoes
            if c.type == socket.SOCK_DGRAM and c.laddr}


def _outbound_ip() -> str | None:
    """IP da interface que atende a internet, que e' onde o jogo fala."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 53))
        return s.getsockname()[0]
    except OSError:
        return None
    finally:
        s.close()


def sniff_peer(ports: set[int], seconds: float = SNIFF_S) -> tuple[str, int] | None:
    """Par (ip, porta) que mais trocou pacotes com essas portas locais."""
    if not ports or not available():
        return None
    host = _outbound_ip()
    if host is None:
        return None

    raw = None
    contagem: collections.Counter = collections.Counter()
    try:
        raw = socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_IP)
        raw.bind((host, 0))
        raw.setsockopt(socket.IPPROTO_IP, socket.IP_HDRINCL, 1)
        raw.ioctl(socket.SIO_RCVALL, socket.RCVALL_ON)
        raw.settimeout(0.5)
        fim = time.monotonic() + seconds
        while time.monotonic() < fim:
            try:
                dados = raw.recvfrom(65535)[0]
            except (TimeoutError, OSError):
                continue
            if len(dados) < 28:
                continue
            ihl = (dados[0] & 0x0F) * 4
            if dados[9] != _UDP or len(dados) < ihl + 8:
                continue
            sport, dport = struct.unpack("!HH", dados[ihl:ihl + 4])
            if sport in ports:
                contagem[(socket.inet_ntoa(dados[16:20]), dport)] += 1
            elif dport in ports:
                contagem[(socket.inet_ntoa(dados[12:16]), sport)] += 1
    except OSError as e:
        _log.info("nao consegui farejar o trafego: %s", e)
        return None
    finally:
        if raw is not None:
            try:
                raw.ioctl(socket.SIO_RCVALL, socket.RCVALL_OFF)
            except OSError:
                pass
            raw.close()

    if not contagem:
        return None
    (ip, porta), pacotes = contagem.most_common(1)[0]
    if pacotes < MIN_PACKETS:
        return None
    return ip, porta


class PeerFinder:
    """Mantem, em segundo plano, o servidor do processo que estiver sendo vigiado."""

    def __init__(self) -> None:
        self._pid = 0
        self._peer: tuple[str, int] | None = None
        self._checked_pid = 0
        self._checked_at = 0.0
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is None and available():
            self._thread = threading.Thread(target=self._loop, name="peer", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()

    def watch(self, pid: int) -> None:
        """Define o processo de interesse. Zero desliga a busca.

        O cache so' e' jogado fora quando o alvo passa a ser OUTRO processo: o
        jogo some e volta da lista a todo instante (basta perder o foco), e
        limpar a cada piscada mandaria farejar de novo sem necessidade.
        """
        with self._lock:
            if pid == self._pid:
                return
            self._pid = pid
            if pid and pid != self._checked_pid:
                self._peer = None
                self._checked_pid = 0
        self._wake.set()

    @property
    def peer(self) -> tuple[str, int] | None:
        with self._lock:
            return self._peer if self._pid and self._pid == self._checked_pid else None

    def _loop(self) -> None:
        while not self._stop.is_set():
            with self._lock:
                pid = self._pid
                ja_visto = pid == self._checked_pid
                idade = time.monotonic() - self._checked_at
            if not pid or (ja_visto and idade < REFRESH_S):
                self._wake.wait(2.0)
                self._wake.clear()
                continue

            portas = local_ports(pid)
            achado = sniff_peer(portas) if portas else None
            with self._lock:
                if pid == self._pid:                 # o alvo pode ter mudado no meio
                    self._checked_pid = pid
                    self._checked_at = time.monotonic()
                    if achado is not None:
                        self._peer = achado
            if achado is not None:
                _log.info("servidor do pid %s: %s:%s", pid, achado[0], achado[1])
