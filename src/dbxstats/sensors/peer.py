"""Descobre com qual servidor um jogo esta' falando.

O Windows nao guarda o endereco remoto na tabela de UDP: `netstat` e psutil
mostram as portas locais do processo e mais nada. Como jogo online quase sempre
e' UDP, ficar so' na tabela deixa o ping apontado para um DNS publico, que nao
diz nada sobre a partida.

A saida e' cruzar as duas metades da informacao: a porta local sai da tabela por
processo, e o outro lado da conversa sai do trafego. Um socket raw em modo
promiscuo (SIO_RCVALL, exige admin) ve os pacotes; casando pela porta local,
sobra o endereco do servidor.

A varredura e' curta e espacada de proposito: alguns segundos bastam para o par
mais falante aparecer, e o resultado vale por bastante tempo: servidor de
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


RTT_PERCENTILE = 0.10
"""Percentil usado como RTT.

O intervalo entre o que sai e a resposta nunca e' menor que a ida e volta real,
mas pode ser bem maior: o servidor responde no tick dele, nao no instante em que
o pacote chega. Por isso a estimativa mora bem embaixo na distribuicao: o
minimo seria refem de um pacote sortudo, e a mediana ja' carrega a cadencia do
servidor inteira.
"""
RTT_CEILING_MS = 1500.0
"""Acima disso nao e' resposta, e' o proximo ciclo do jogo."""
MIN_RTT_PAIRS = 6
MEASURE_S = 1.5
"""Escuta de medicao. Curta: em jogo de tempo real da' dezenas de idas e voltas."""
MEASURE_GAP_S = 2.0
"""Descanso entre medicoes, para nao ficar com o socket raw aberto o tempo todo."""
RTT_STALE_S = 12.0
"""Sem medida nova por tanto tempo, o numero vira mentira e some."""


def available() -> bool:
    return hasattr(socket, "SIO_RCVALL")


def estimate_rtt(events: list[tuple[float, bool]]) -> tuple[float | None, float | None]:
    """Latencia e jitter a partir do vaivem dos pacotes.

    `events` e' a linha do tempo do que passou: (instante, saiu_da_maquina). Cada
    envio e' casado com a primeira resposta que vem depois dele: em jogo de
    tempo real o cliente manda input e o servidor devolve estado, entao esse
    intervalo contem a ida e volta.

    Vale mesmo quando o servidor bloqueia ICMP, porque nao ha' sonda nenhuma: o
    numero sai do trafego que o jogo ja' esta' fazendo.
    """
    deltas: list[float] = []
    ultimo_envio: float | None = None
    for instante, saiu in events:
        if saiu:
            if ultimo_envio is None:
                ultimo_envio = instante
        elif ultimo_envio is not None:
            ida_volta = (instante - ultimo_envio) * 1000.0
            ultimo_envio = None
            if 0.0 < ida_volta <= RTT_CEILING_MS:
                deltas.append(ida_volta)
    if len(deltas) < MIN_RTT_PAIRS:
        return None, None

    ordenado = sorted(deltas)
    rtt = ordenado[min(len(ordenado) - 1, int(len(ordenado) * RTT_PERCENTILE))]
    # Jitter e' variacao percebida: media da diferenca entre medidas seguidas,
    # na ordem em que aconteceram (nao na ordenada).
    variacao = sum(abs(deltas[i] - deltas[i - 1]) for i in range(1, len(deltas)))
    return round(rtt, 1), round(variacao / (len(deltas) - 1), 1)


def local_ports(pid: int) -> set[int]:
    """Portas UDP que o processo abriu: a metade da informacao que o Windows da'."""
    return local_endpoints(pid)[0]


def local_endpoints(pid: int) -> tuple[set[int], set[str]]:
    """Portas e enderecos locais do processo.

    O endereco importa quando o jogo sai por outra interface (VPN, adaptador
    virtual) porque e' nela que o trafego dele passa, e nao na rota padrao.
    """
    if pid <= 4:
        return set(), set()
    try:
        conexoes = psutil.Process(pid).net_connections(kind="inet")
    except (psutil.Error, OSError):
        return set(), set()
    portas: set[int] = set()
    enderecos: set[str] = set()
    for c in conexoes:
        if c.type != socket.SOCK_DGRAM or not c.laddr:
            continue
        portas.add(c.laddr.port)
        ip = getattr(c.laddr, "ip", "")
        if ip and not ip.startswith(("0.", "127.", "::")):
            enderecos.add(ip)
    return portas, enderecos


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


def sniff_peer(ports: set[int], seconds: float = SNIFF_S,
               bind_ip: str | None = None) -> tuple[str, int] | None:
    """Par (ip, porta) que mais trocou pacotes com essas portas locais."""
    contagem, _ = capture(ports, seconds, bind_ip)
    if not contagem:
        return None
    (ip, porta), pacotes = contagem.most_common(1)[0]
    return (ip, porta) if pacotes >= MIN_PACKETS else None


def capture(ports: set[int], seconds: float, bind_ip: str | None = None,
            peer_ip: str | None = None) -> tuple[collections.Counter, list[tuple[float, bool]]]:
    """Uma passada de escuta.

    Devolve quem falou com o processo (para descobrir o servidor) e, quando
    `peer_ip` e' dado, a linha do tempo do vaivem com ele, que e' de onde sai a
    latencia sem sondar nada.
    """
    vazio: collections.Counter = collections.Counter()
    if not ports or not available():
        return vazio, []
    host = bind_ip or _outbound_ip()
    if host is None:
        return vazio, []

    raw = None
    contagem: collections.Counter = collections.Counter()
    eventos: list[tuple[float, bool]] = []
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
                outro = socket.inet_ntoa(dados[16:20])
                contagem[(outro, dport)] += 1
                saiu = True
            elif dport in ports:
                outro = socket.inet_ntoa(dados[12:16])
                contagem[(outro, sport)] += 1
                saiu = False
            else:
                continue
            if peer_ip is not None and outro == peer_ip:
                eventos.append((time.perf_counter(), saiu))
    except OSError as e:
        _log.info("nao consegui farejar o trafego: %s", e)
        return vazio, []
    finally:
        if raw is not None:
            try:
                raw.ioctl(socket.SIO_RCVALL, socket.RCVALL_OFF)
            except OSError:
                pass
            raw.close()

    return contagem, eventos


class PeerFinder:
    """Mantem, em segundo plano, o servidor do processo que estiver sendo vigiado."""

    def __init__(self) -> None:
        self._pid = 0
        self._peer: tuple[str, int] | None = None
        self._checked_pid = 0
        self._checked_at = 0.0
        self._rtt: float | None = None
        self._jitter: float | None = None
        self._rtt_at = 0.0
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
                self._rtt = self._jitter = None
        self._wake.set()

    @property
    def peer(self) -> tuple[str, int] | None:
        with self._lock:
            return self._peer if self._pid and self._pid == self._checked_pid else None

    @property
    def latency(self) -> tuple[float | None, float | None]:
        """(rtt, jitter) medidos no proprio trafego do jogo, sem sondar nada."""
        with self._lock:
            if not self._pid or self._pid != self._checked_pid:
                return None, None
            return self._rtt, self._jitter

    def _loop(self) -> None:
        while not self._stop.is_set():
            with self._lock:
                pid = self._pid
                peer = self._peer if pid == self._checked_pid else None
                vencido = time.monotonic() - self._checked_at > REFRESH_S
            if not pid:
                self._wake.wait(2.0)
                self._wake.clear()
                continue

            portas, enderecos = local_endpoints(pid)
            if not portas:
                self._wake.wait(3.0)
                self._wake.clear()
                continue
            # Escuta na interface do proprio jogo quando ele declara uma; com VPN
            # ligada a rota padrao nao e' por onde os pacotes dele passam.
            bind_ip = next(iter(enderecos), None)
            # Uma passada serve para as duas coisas: descobrir o servidor (quem
            # mais falou) e cronometrar o vaivem com ele.
            alvo = None if (peer is None or vencido) else peer[0]
            janela = SNIFF_S if alvo is None else MEASURE_S
            contagem, eventos = capture(portas, janela, bind_ip, alvo)

            achado = None
            if contagem:
                (ip, porta), pacotes = contagem.most_common(1)[0]
                if pacotes >= MIN_PACKETS:
                    achado = (ip, porta)
            rtt, jitter = estimate_rtt(eventos)

            with self._lock:
                if pid != self._pid:                 # o alvo mudou no meio da escuta
                    continue
                self._checked_pid = pid
                if achado is not None and (self._peer is None or vencido):
                    if achado != self._peer:
                        _log.info("servidor do pid %s: %s:%s", pid, achado[0], achado[1])
                    self._peer = achado
                    self._checked_at = time.monotonic()
                if rtt is not None:
                    self._rtt, self._jitter = rtt, jitter
                    self._rtt_at = time.monotonic()
                elif time.monotonic() - self._rtt_at > RTT_STALE_S:
                    self._rtt = self._jitter = None
            self._wake.wait(MEASURE_GAP_S)
            self._wake.clear()
