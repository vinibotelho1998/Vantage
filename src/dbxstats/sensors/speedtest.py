"""Teste de velocidade da conexao, no espirito do Speedtest.

Tres medidas em sequencia — latencia, download e upload — cada uma com varios
fluxos em paralelo. Fluxo unico nao serve para link rapido: a janela do TCP e o
RTT limitam um socket sozinho bem antes do limite da banda, e o resultado sai a
metade do que a assinatura entrega.

O comeco de cada fase e' jogado fora de proposito. O TCP entra devagar (slow
start) e leva quase um segundo para achar o ritmo; contar esse pedaco e' o que
faz um link de 600 Mbps aparecer como 200. Por isso a conta so' olha as marcas
depois do aquecimento.

A latencia e' medida com um connect TCP puro, e nao com um GET: o handshake TLS
custa mais duas idas e voltas, e um numero tres vezes maior que o ping real seria
so' mentira com cara de precisao.

Nada aqui depende do Qt. O motor roda em thread propria e quem desenha le
`snapshot()` na cadencia que quiser.
"""
from __future__ import annotations

import io
import os
import random
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from .. import log

_log = log.get("speedtest")

# ── endpoints ─────────────────────────────────────────────────────────────────
URL_DOWNLOAD = "https://speed.cloudflare.com/__down?bytes=90000000"
"""Servidor principal: anycast, entao o PoP que atende e' o mais perto de casa.

O tamanho nao e' arbitrario — a Cloudflare devolve 403 para pedido de 100 MB ou
mais, e 90 MB da' folga para o fluxo mais rapido nao esgotar o arquivo no meio
da janela de medicao.
"""
URL_DOWNLOAD_RESERVA = "https://ash-speed.hetzner.com/100MB.bin"
"""Plano B: arquivo estatico num datacenter fixo (Ashburn).

So' entra quando a Cloudflare nao responde. Como e' um destino unico e distante,
o numero costuma ficar ABAIXO do link real — quem usa a reserva recebe um aviso
junto, para nao ler o resultado como se fosse a medicao boa.
"""
URL_UPLOAD = "https://speed.cloudflare.com/__up"
"""Envio nao tem plano B: endpoint que aceita e descarta corpo grande e' raro.

Quando ele falha, o teste devolve download e latencia com um aviso dizendo que o
upload ficou de fora — melhor faltar um numero do que inventar um.
"""

# ── parametros da medicao ────────────────────────────────────────────────────
FLUXOS = 4
DURACAO_S = 6.0
AQUECIMENTO_S = 1.5
"""Tempo descartado no inicio de cada fase (slow start do TCP)."""
JANELA_MINIMA_S = 0.5
"""Abaixo disso a divisao vira ruido, nao medida."""
AMOSTRAGEM_S = 0.1
SONDAS = 6
TIMEOUT_S = 10.0
BLOCO = 1 << 16
PEDACO_UPLOAD = 60_000_000
"""Corpo prometido em cada POST.

Generoso de proposito: sobrar nao custa nada (a fase acaba e o envio e' abortado
no meio), mas faltar custa um handshake TLS novo a cada pedaco — num link de
upload rapido esse vaivem apareceria como buraco na medicao.
"""
PORTA_TLS = 443

# ── fases ────────────────────────────────────────────────────────────────────
FASE_OCIOSO = "ocioso"
FASE_LATENCIA = "latencia"
FASE_DOWNLOAD = "download"
FASE_UPLOAD = "upload"
FASE_PRONTO = "pronto"
FASE_ERRO = "erro"
FASE_CANCELADO = "cancelado"

FASES = (FASE_LATENCIA, FASE_DOWNLOAD, FASE_UPLOAD)
PESOS = {FASE_LATENCIA: 0.08, FASE_DOWNLOAD: 0.52, FASE_UPLOAD: 0.40}
"""Quanto cada fase ocupa da barra. Download pesa mais porque demora mais."""

_CABECALHOS = {"User-Agent": "DBXStats/3.0", "Cache-Control": "no-cache",
               "Pragma": "no-cache"}


# ── matematica ───────────────────────────────────────────────────────────────
def mbps(transferido: float, segundos: float) -> float | None:
    """Megabits por segundo — a unidade em que a operadora vende o plano.

    Byte vira bit e o divisor e' 1e6, nao 2^20: comparar com "300 mega" da conta
    de luz da internet so' faz sentido na escala decimal.
    """
    if segundos <= 0 or transferido < 0:
        return None
    return round(transferido * 8.0 / segundos / 1e6, 2)


def taxa_estavel(amostras: list[tuple[float, int]], aquecimento: float = AQUECIMENTO_S,
                 janela_minima: float = JANELA_MINIMA_S) -> float | None:
    """Taxa do trecho ja' aquecido, em Mbps.

    `amostras` sao marcas (instante, bytes acumulados por todos os fluxos). A
    conta usa so' a primeira e a ultima marca uteis: entre elas o total e' exato,
    e qualquer media de fatias intermediarias so' adicionaria ruido de agendamento.

    Quando o teste foi curto demais para sobrar algo depois do aquecimento, vale
    a serie inteira — numero conservador e' melhor que travessao.
    """
    if len(amostras) < 2:
        return None
    inicio = amostras[0][0]
    uteis = [a for a in amostras if a[0] >= inicio + aquecimento]
    if len(uteis) < 2:
        uteis = amostras
    t0, b0 = uteis[0]
    t1, b1 = uteis[-1]
    if t1 - t0 < janela_minima or b1 <= b0:
        return None
    return mbps(b1 - b0, t1 - t0)


def taxa_instantanea(amostras: list[tuple[float, int]], janela: float = 1.0) -> float | None:
    """Taxa dos ultimos instantes — e' o numero que corre na tela enquanto mede."""
    if len(amostras) < 2:
        return None
    corte = amostras[-1][0] - janela
    recentes = [a for a in amostras if a[0] >= corte]
    if len(recentes) < 2:
        recentes = amostras[-2:]
    t0, b0 = recentes[0]
    t1, b1 = recentes[-1]
    if t1 <= t0 or b1 < b0:
        return None
    return mbps(b1 - b0, t1 - t0)


def latencia(medidas_ms: list[float]) -> tuple[float | None, float | None]:
    """(latencia, jitter) a partir das sondas.

    A latencia e' a MENOR ida e volta observada. Tudo que passa disso e' fila no
    caminho ou servidor ocupado, nunca velocidade da luz sobrando: o piso e' a
    unica amostra que fala so' da rede.

    O jitter e' a MEDIANA da diferenca entre sondas seguidas, e nao a media. Com
    meia duzia de sondas, um unico connect que caiu numa fila (16, 16, 17, 40,
    16 ms — acontece o tempo todo) puxava a media para 10 ms e pintava de instavel
    uma conexao que oscila 1 ms. A mediana descreve a oscilacao tipica, que e' o
    que a pessoa sente.
    """
    validas = [m for m in medidas_ms if m is not None and m >= 0]
    if not validas:
        return None, None
    piso = round(min(validas), 1)
    if len(validas) < 2:
        return piso, None
    diferencas = sorted(abs(validas[i] - validas[i - 1]) for i in range(1, len(validas)))
    return piso, round(diferencas[len(diferencas) // 2], 1)


def progresso(fase: str, fracao: float) -> float:
    """Posicao da barra: o que ja' passou mais o pedaco da fase atual."""
    if fase == FASE_PRONTO:
        return 1.0
    if fase not in PESOS:
        return 0.0
    andado = 0.0
    for nome in FASES:
        if nome == fase:
            return round(andado + PESOS[nome] * max(0.0, min(1.0, fracao)), 4)
        andado += PESOS[nome]
    return andado


def mensagem_de_erro(exc: BaseException) -> str:
    """Traduz a falha para uma frase que explica o que fazer.

    O usuario nao precisa saber o que e' gaierror; precisa saber se o problema e'
    a internet dele ou o servidor de teste. Numero nenhum aparece junto: zero
    Mbps com cara de medicao e' pior que um erro honesto.
    """
    motivo = getattr(exc, "reason", exc)
    if isinstance(motivo, socket.gaierror) or isinstance(exc, socket.gaierror):
        return "sem conexão: não consegui resolver o endereço do servidor de teste"
    if isinstance(motivo, TimeoutError) or isinstance(exc, TimeoutError):
        return "o servidor de teste não respondeu a tempo"
    if isinstance(exc, urllib.error.HTTPError):
        return f"o servidor de teste recusou o pedido (HTTP {exc.code})"
    if isinstance(motivo, ConnectionError) or isinstance(exc, ConnectionError):
        return "a conexão com o servidor de teste caiu no meio do teste"
    if isinstance(exc, OSError) and getattr(exc, "errno", None) is not None:
        return f"a rede recusou a conexão ({exc.strerror or exc})"
    return f"não consegui medir: {exc}"


def _sem_cache(url: str) -> str:
    """Impede que um proxy no caminho sirva o arquivo do cache dele.

    Cache no meio do caminho nao mede a internet, mede a rede da casa — e o
    numero sai absurdamente alto sem nenhum aviso de que e' mentira.
    """
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}nocache={random.getrandbits(32):08x}"


class Contador:
    """Bytes que os fluxos ja' moveram, somados com trava."""

    def __init__(self) -> None:
        self._total = 0
        self._lock = threading.Lock()

    def somar(self, quantos: int) -> None:
        with self._lock:
            self._total += quantos

    @property
    def total(self) -> int:
        with self._lock:
            return self._total


class _Cancelado(Exception):
    """Sinal interno: o usuario mandou parar no meio de uma transferencia."""


class _CorpoContado(io.RawIOBase):
    """Corpo do POST gerado na hora, contando o que ja' foi entregue ao socket.

    Materializar 20 MB por fluxo seria desperdicio: o mesmo bloco aleatorio e'
    reenviado ate completar o tamanho prometido no Content-Length. Aleatorio, e
    nao zeros, porque middlebox que comprime na marra transformaria o teste numa
    medicao de compressao.
    """

    def __init__(self, tamanho: int, contar, cancelado, bloco: bytes) -> None:
        super().__init__()
        self._resta = tamanho
        self._contar = contar
        self._cancelado = cancelado
        self._bloco = bloco

    def readable(self) -> bool:
        return True

    def read(self, tamanho: int = -1) -> bytes:
        if self._cancelado():
            # Estourar aqui e' o que fecha o socket na hora: o urllib derruba a
            # conexao quando o corpo levanta. Devolver b"" deixaria o servidor
            # esperando o resto do Content-Length ate o timeout.
            raise _Cancelado
        if self._resta <= 0:
            return b""
        quanto = len(self._bloco) if tamanho is None or tamanho < 0 else tamanho
        pedaco = self._bloco[:min(quanto, self._resta, len(self._bloco))]
        self._resta -= len(pedaco)
        self._contar(len(pedaco))
        return pedaco


class Rede:
    """Transporte HTTP do teste, isolado para o teste automatizado poder trocar."""

    def __init__(self) -> None:
        self._abertos: set = set()
        self._lock = threading.Lock()

    def abortar(self) -> None:
        """Fecha na marra tudo que estiver aberto.

        Sem isso o cancelamento so' vale quando o read() em curso volta — e num
        socket travado isso e' o timeout inteiro. Fechar o app no meio de um
        teste deixaria a conexao de pe' esperando dado que ninguem quer mais.
        """
        with self._lock:
            abertos, self._abertos = list(self._abertos), set()
        for resp in abertos:
            try:
                resp.close()
            except Exception:  # noqa: BLE001 — fechar o que ja' morreu nao e' erro
                pass

    def _abrir(self, req: urllib.request.Request, timeout: float):
        resp = urllib.request.urlopen(req, timeout=timeout)
        with self._lock:
            self._abertos.add(resp)
        return resp

    def _fechar(self, resp) -> None:
        with self._lock:
            self._abertos.discard(resp)
        try:
            resp.close()
        except Exception:  # noqa: BLE001
            pass

    def sondar(self, host: str, porta: int, timeout: float) -> float:
        """Ida e volta ate o servidor, em ms, via connect TCP.

        O DNS fica fora do cronometro de proposito: resolver o nome custa uma
        consulta que nao tem nada a ver com a distancia ate o servidor, e era o
        que fazia a primeira sonda sair dobrada e inflar o jitter inteiro.
        """
        familia, tipo, proto, _, endereco = socket.getaddrinfo(
            host, porta, type=socket.SOCK_STREAM)[0]
        s = socket.socket(familia, tipo, proto)
        s.settimeout(timeout)
        try:
            inicio = time.perf_counter()
            s.connect(endereco)
            return (time.perf_counter() - inicio) * 1000.0
        finally:
            s.close()

    def baixar(self, url: str, cancelado, contar, timeout: float) -> None:
        req = urllib.request.Request(_sem_cache(url), headers=_CABECALHOS)
        resp = self._abrir(req, timeout)
        try:
            while not cancelado():
                bloco = resp.read(BLOCO)
                if not bloco:
                    return
                contar(len(bloco))
        finally:
            self._fechar(resp)

    def enviar(self, url: str, cancelado, contar, timeout: float, tamanho: int) -> None:
        corpo = _CorpoContado(tamanho, contar, cancelado, os.urandom(BLOCO))
        cabecalhos = dict(_CABECALHOS)
        cabecalhos["Content-Type"] = "application/octet-stream"
        cabecalhos["Content-Length"] = str(tamanho)
        req = urllib.request.Request(_sem_cache(url), data=corpo, method="POST",
                                     headers=cabecalhos)
        resp = self._abrir(req, timeout)
        try:
            resp.read(BLOCO)
        finally:
            self._fechar(resp)


class TesteDeVelocidade:
    """Maquina de estados do teste: latencia, download, upload.

    Roda numa thread so' (mais as dos fluxos), publica o andamento num snapshot
    protegido por trava e para na hora quando mandam parar. Nenhuma thread e'
    non-daemon e nenhum socket sobrevive ao cancelamento — fechar o app no meio
    de um teste nao pode segurar o processo vivo.
    """

    def __init__(self, rede: Rede | None = None, fluxos: int = FLUXOS,
                 duracao: float = DURACAO_S, aquecimento: float = AQUECIMENTO_S,
                 janela_minima: float = JANELA_MINIMA_S, sondas: int = SONDAS,
                 urls_download: tuple[str, ...] = (URL_DOWNLOAD, URL_DOWNLOAD_RESERVA),
                 url_upload: str = URL_UPLOAD, timeout: float = TIMEOUT_S) -> None:
        self._rede = rede or Rede()
        self._fluxos = max(1, int(fluxos))
        self._duracao = float(duracao)
        self._aquecimento = float(aquecimento)
        self._janela_minima = float(janela_minima)
        self._sondas = max(1, int(sondas))
        self._urls_download = tuple(urls_download)
        self._url_upload = url_upload
        self._timeout = float(timeout)

        self._lock = threading.Lock()
        self._parar = threading.Event()
        self._thread: threading.Thread | None = None
        self._estado = self._zerado()

    # ── estado ───────────────────────────────────────────────────────────────
    def _zerado(self) -> dict:
        return {"fase": FASE_OCIOSO, "rodando": False, "progresso": 0.0,
                "parcial": None, "download": None, "upload": None,
                "ping": None, "jitter": None, "erro": None, "aviso": None,
                "servidor": _host(self._urls_download[0]), "quando": None}

    def _publicar(self, **campos) -> None:
        with self._lock:
            self._estado.update(campos)

    def snapshot(self) -> dict:
        with self._lock:
            return dict(self._estado)

    @property
    def rodando(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    # ── controle ─────────────────────────────────────────────────────────────
    def start(self) -> bool:
        """Comeca um teste. Devolve False se ja' havia um rodando."""
        if self.rodando:
            return False
        self._parar.clear()
        with self._lock:
            self._estado = self._zerado()
            self._estado.update(fase=FASE_LATENCIA, rodando=True)
        self._thread = threading.Thread(target=self._executar, name="speedtest", daemon=True)
        self._thread.start()
        return True

    def cancel(self) -> None:
        self._parar.set()
        self._rede.abortar()

    def stop(self, timeout: float = 2.0) -> None:
        """Encerra de vez — usado ao fechar o app."""
        self.cancel()
        self.aguardar(timeout)

    def aguardar(self, timeout: float = 30.0) -> bool:
        """Espera o teste acabar. Devolve False se estourou o prazo."""
        thread = self._thread
        if thread is None:
            return True
        thread.join(timeout)
        return not thread.is_alive()

    # ── execucao ─────────────────────────────────────────────────────────────
    def _executar(self) -> None:
        try:
            self._medir_latencia()
            baixado, erro_dl, reserva = self._fase_download()
            enviado, erro_ul = self._fase_upload()
            self._concluir(baixado, erro_dl, reserva, enviado, erro_ul)
        except Exception as e:  # noqa: BLE001 — thread solta nao pode morrer calada
            _log.warning("teste de velocidade quebrou: %s", e)
            self._publicar(fase=FASE_ERRO, rodando=False, parcial=None,
                           erro=mensagem_de_erro(e), progresso=1.0)
        finally:
            self._publicar(rodando=False, parcial=None)

    def _concluir(self, baixado, erro_dl, reserva, enviado, erro_ul) -> None:
        if self._parar.is_set():
            self._publicar(fase=FASE_CANCELADO, rodando=False, parcial=None,
                           aviso="Teste interrompido.")
            return
        if baixado is None:
            self._publicar(fase=FASE_ERRO, rodando=False, parcial=None, progresso=1.0,
                           erro=erro_dl or "não consegui medir o download")
            return
        avisos = []
        if reserva:
            avisos.append("Servidor principal fora do ar: medi pelo reserva, "
                          "o valor pode sair abaixo do real.")
        if enviado is None:
            avisos.append(f"Upload ficou de fora — {erro_ul or 'servidor não respondeu'}.")
        self._publicar(fase=FASE_PRONTO, rodando=False, parcial=None, progresso=1.0,
                       quando=time.strftime("%H:%M"),
                       aviso=" ".join(avisos) if avisos else None)

    # ── latencia ─────────────────────────────────────────────────────────────
    def _medir_latencia(self) -> None:
        host = _host(self._urls_download[0])
        medidas: list[float] = []
        for i in range(self._sondas):
            if self._parar.is_set():
                return
            try:
                medidas.append(self._rede.sondar(host, PORTA_TLS, min(self._timeout, 3.0)))
            except OSError:
                pass            # sonda perdida vira jitter, nao erro: o download decide
            ms, jitter = latencia(medidas)
            self._publicar(ping=ms, jitter=jitter, servidor=host,
                           progresso=progresso(FASE_LATENCIA, (i + 1) / self._sondas))
            self._parar.wait(0.05)

    # ── transferencia ────────────────────────────────────────────────────────
    def _fase_download(self) -> tuple[float | None, str | None, bool]:
        """Tenta o servidor principal e, so' se ele falhar, o reserva."""
        self._publicar(fase=FASE_DOWNLOAD)
        ultimo_erro = None
        for indice, url in enumerate(self._urls_download):
            if self._parar.is_set():
                return None, None, False
            self._publicar(servidor=_host(url))
            taxa, erro = self._transferir(FASE_DOWNLOAD, url)
            if taxa is not None:
                self._publicar(download=taxa)
                return taxa, None, indice > 0
            ultimo_erro = erro
        return None, ultimo_erro, False

    def _fase_upload(self) -> tuple[float | None, str | None]:
        if self._parar.is_set():
            return None, None
        self._publicar(fase=FASE_UPLOAD)
        taxa, erro = self._transferir(FASE_UPLOAD, self._url_upload)
        if taxa is not None:
            self._publicar(upload=taxa)
        return taxa, erro

    def _transferir(self, fase: str, url: str) -> tuple[float | None, str | None]:
        """Uma fase inteira: sobe os fluxos, amostra o total e fecha tudo."""
        contador = Contador()
        fim_da_fase = threading.Event()
        erros: list[BaseException] = []

        def cancelado() -> bool:
            return fim_da_fase.is_set() or self._parar.is_set()

        threads = [threading.Thread(target=self._fluxo, name=f"speed-{fase}-{i}", daemon=True,
                                    args=(fase, url, cancelado, contador, erros))
                   for i in range(self._fluxos)]
        for t in threads:
            t.start()

        amostras: list[tuple[float, int]] = []
        inicio = time.monotonic()
        try:
            while True:
                agora = time.monotonic()
                decorrido = agora - inicio
                amostras.append((agora, contador.total))
                if decorrido >= self._duracao or self._parar.is_set():
                    break
                if not any(t.is_alive() for t in threads):
                    break       # todos os fluxos cairam: nao adianta esperar o relogio
                self._publicar(progresso=progresso(fase, decorrido / self._duracao),
                               parcial=taxa_instantanea(amostras))
                self._parar.wait(AMOSTRAGEM_S)
        finally:
            fim_da_fase.set()
            for t in threads:
                t.join(3.0)

        if self._parar.is_set():
            return None, None
        taxa = taxa_estavel(amostras, self._aquecimento, self._janela_minima)
        if taxa is None:
            erro = mensagem_de_erro(erros[0]) if erros else "o servidor de teste não enviou dados"
            _log.info("fase %s sem resultado (%s)", fase, erro)
            return None, erro
        return taxa, None

    def _fluxo(self, fase: str, url: str, cancelado, contador: Contador,
               erros: list) -> None:
        """Um fluxo paralelo: reabre a conexao ate a fase acabar.

        Reabrir e' necessario porque o arquivo do servidor tem tamanho fixo — num
        link rapido ele acaba antes do relogio, e sem a repeticao a segunda metade
        da janela seria medida como zero.
        """
        while not cancelado():
            try:
                if fase == FASE_DOWNLOAD:
                    self._rede.baixar(url, cancelado, contador.somar, self._timeout)
                else:
                    self._rede.enviar(url, cancelado, contador.somar, self._timeout,
                                      PEDACO_UPLOAD)
            except _Cancelado:
                return
            except Exception as e:  # noqa: BLE001
                if not cancelado():
                    erros.append(e)
                return


def _host(url: str) -> str:
    return urllib.parse.urlsplit(url).hostname or url
