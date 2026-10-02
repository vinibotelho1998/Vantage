"""Latencia, jitter e perda de pacotes.

Por padrao mede contra um host fixo (DNS publico). Quando ha' jogo em foco, o
alvo passa a ser o servidor com que o proprio jogo esta' falando, que e' a
latencia que importa para quem esta' jogando, e nao a de um DNS qualquer.

A medicao prefere ICMP: servidor de jogo quase sempre e' UDP, e abrir TCP na
porta dele nao mede nada. TCP connect fica como reserva.
"""
from __future__ import annotations

import ipaddress
import socket
import threading
import time
from collections import deque

import psutil

from ..platform import icmp


class PingMonitor:
    """Mede RTT continuamente e mantem uma janela para calcular jitter e perda."""

    def __init__(self, host: str = "8.8.8.8", port: int = 53, samples: int = 5,
                 interval: float = 2.0) -> None:
        self._host = host
        self._port = port
        self._samples = samples
        self._interval = interval
        self._ms: float | None = None
        self._jitter: float | None = None
        self._loss: float | None = None
        self._best: float | None = None
        self._worst: float | None = None
        self._auto_host: str | None = None
        self._auto_port = 0
        self._auto_label = ""
        self._measured: float | None = None
        self._measured_jitter: float | None = None
        self._measured_at = 0.0
        self._mudos: set[str] = set()
        """Alvos que nao responderam a nada. Servidor de jogo costuma ignorar ICMP,
        e insistir neles pintaria 100% de perda numa conexao perfeitamente saudavel."""
        self._history: deque[float] = deque(maxlen=60)
        self._lock = threading.RLock()
        self._generation = 0
        self._measured_label = ""
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def configure(self, host: str, port: int) -> None:
        with self._lock:
            changed = host != self._host or int(port) != self._port
            self._host = host or self._host
            self._port = int(port) or self._port
            if changed:
                self._clear_measurements()

    def set_auto_target(self, host: str | None, port: int = 0, label: str = "") -> None:
        """Alvo do jogo em foco. `None` volta para o host das configuracoes."""
        with self._lock:
            if host is not None and host in self._mudos:
                # O alvo de antes pode ser de outra partida. Mesmo quando o novo
                # nao responde, nao conservar o numero e o rotulo do jogo anterior.
                host, port, label = None, 0, ""
            if host == self._auto_host and int(port or 0) == self._auto_port:
                self._auto_label = label
                return
            self._auto_host = host
            self._auto_port = int(port or 0)
            self._auto_label = label
            self._clear_measurements()

    def set_measured(self, rtt: float | None, jitter: float | None, label: str) -> None:
        """Latencia medida no proprio trafego do jogo.

        Vale mais que a sonda: nao depende do servidor responder ICMP e mede o
        caminho que o jogo realmente usa. Quando existe, manda na leitura.
        """
        with self._lock:
            self._measured = rtt
            self._measured_jitter = jitter
            self._measured_at = time.monotonic() if rtt is not None else 0.0
            if rtt is not None:
                self._measured_label = label

    def _measured_fresh(self) -> bool:
        return self._measured is not None and (time.monotonic() - self._measured_at) < 15.0

    @property
    def measuring_game(self) -> bool:
        with self._lock:
            return self._measured_fresh()

    @property
    def target_label(self) -> str:
        """Nome do servidor do jogo, quando ha' um. Vazio no resto do tempo.

        Nao devolve mais o alvo de reserva. Sem partida identificada o ping vai
        para um DNS publico so' para ter alguma referencia de latencia, e mostrar
        "8.8.8.8" no overlay dava a entender que aquele numero tinha a ver com o
        jogo. Sem rotulo, sobra so' o ping: que e' o que ele e'.
        """
        with self._lock:
            return self._measured_label if self._measured_fresh() else self._auto_label

    @property
    def following_game(self) -> bool:
        with self._lock:
            return bool(self._auto_host)

    def _target(self) -> tuple[str, int]:
        with self._lock:
            if self._auto_host:
                return self._auto_host, self._auto_port
            return self._host, self._port

    def read(self) -> dict:
        with self._lock:
            if not self._measured_fresh():
                return {"ms": self._ms, "jitter": self._jitter, "loss": self._loss,
                        "best": self._best, "worst": self._worst}
            # Uma medida do jogo nao pode herdar RTT, perda ou extremos do DNS de reserva.
            return {"ms": self._measured, "jitter": self._measured_jitter,
                    "loss": None, "best": None, "worst": None}

    def _clear_measurements(self) -> None:
        self._generation += 1
        self._ms = self._jitter = self._loss = self._best = self._worst = None
        self._measured = self._measured_jitter = None
        self._measured_at = 0.0
        self._measured_label = ""
        self._history.clear()

    def history(self) -> list[float]:
        with self._lock:
            return list(self._history)

    def start(self) -> None:
        if self._thread is None:
            self._thread = threading.Thread(target=self._loop, name="ping", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.is_set():
            with self._lock:
                host, port = self._target()
                generation = self._generation
            results: list[float | None] = []
            for _ in range(self._samples):
                if self._stop.is_set():
                    return
                results.append(_probe(host, port))
                self._stop.wait(0.15)
            self._publish(host, results, port=port, generation=generation)
            self._stop.wait(self._interval)

    def _publish(self, host: str, results: list[float | None], *,
                 port: int | None = None, generation: int | None = None) -> None:
        ok = [r for r in results if r is not None]
        avg = sum(ok) / len(ok) if ok else None
        jitter = None
        if len(ok) > 1:
            jitter = sum(abs(ok[i] - ok[i - 1]) for i in range(1, len(ok))) / (len(ok) - 1)
        loss = round(100.0 * (1 - len(ok) / max(1, len(results))), 1)
        with self._lock:
            target = self._target()
            if host != target[0] or (port is not None and port != target[1]):
                return
            if generation is not None and generation != self._generation:
                return
            if not ok and self._descartar_alvo(host):
                return
            self._ms = None if avg is None else round(avg, 1)
            self._jitter = None if jitter is None else round(jitter, 1)
            self._loss = loss
            if avg is not None:
                self._history.append(round(avg, 1))
                self._best = avg if self._best is None else min(self._best, avg)
                self._worst = avg if self._worst is None else max(self._worst, avg)


    def _descartar_alvo(self, host: str) -> bool:
        """Alvo automatico que nao respondeu nada volta para o host fixo.

        Muito servidor de jogo simplesmente ignora ICMP. Continuar apontado para
        ele mostraria "100% de perda" com a partida rodando lisa, mentira que
        assusta e nao ajuda em nada.
        """
        with self._lock:
            if not self._auto_host or self._auto_host != host:
                return False
            self._mudos.add(host)
            self._auto_host = None
            self._auto_port = 0
            self._auto_label = ""
            self._clear_measurements()
        return True


def _probe(host: str, port: int, timeout: float = 1.5) -> float | None:
    """RTT em ms. ICMP primeiro; TCP so' quando ha' porta e o ICMP nao respondeu."""
    if icmp.available():
        rtt = icmp.ping(host, int(timeout * 1000))
        if rtt is not None:
            return rtt
    if not port:
        return None
    try:
        t = time.perf_counter()
        with socket.create_connection((host, port), timeout=timeout):
            pass
        return (time.perf_counter() - t) * 1000.0
    except ConnectionRefusedError:
        # Recusa e' resposta: o pacote foi e voltou, o servidor so' nao quer TCP
        # nessa porta. Contar como perda mentiria sobre a conexao.
        return (time.perf_counter() - t) * 1000.0
    except OSError:
        return None


_PRIVADO = ("is_private", "is_loopback", "is_multicast", "is_reserved", "is_unspecified")


def _publico(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    if addr.version != 4:
        return False        # o ICMP daqui e' IPv4; alvo v6 viraria "100% de perda"
    return not any(getattr(addr, nome, False) for nome in _PRIVADO)


def game_server(pid: int) -> tuple[str, int] | None:
    """Endereco do servidor com que o processo esta' falando.

    UDP tem preferencia: e' por onde o jogo troca estado com o servidor. TCP
    costuma ser loja, chat ou telemetria: latencia dali nao diz nada sobre a
    partida.
    """
    if pid <= 4:            # System e Idle devolvem a tabela inteira da maquina
        return None
    try:
        conexoes = psutil.Process(pid).net_connections(kind="inet")
    except (psutil.Error, OSError):
        return None
    melhor: tuple[int, str, int] | None = None
    for conexao in conexoes:
        remoto = conexao.raddr
        if not remoto or not _publico(remoto.ip):
            continue
        peso = 2 if conexao.type == socket.SOCK_DGRAM else 1
        if melhor is None or peso > melhor[0]:
            melhor = (peso, remoto.ip, remoto.port)
    return (melhor[1], melhor[2]) if melhor else None
