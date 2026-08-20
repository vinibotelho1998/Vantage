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

Servidor de teste nao e' um so'. Cada fase percorre uma FILA de provedores e para
no primeiro que entregar: quem mede varias vezes seguidas acaba levando HTTP 429
por volume (a Cloudflare corta por ~1 h a partir do excesso), e uma fila de tres
casas independentes e' o que separa "o servidor esta' de castigo" de "a internet
caiu". A fila comeca em Sao Paulo porque so' um servidor perto mede o link de
verdade; o que esta' fora do pais entra como prova de vida, e o numero dele sai
com ressalva.

Falha de uma fase nao apaga as outras, e cada numero e' publicado assim que fecha
— o download aparece na tela antes de o upload comecar. O contrario disso, que e'
segurar tudo e no fim virar um "erro" so', joga fora medida boa e faz o usuario
repetir um teste que ja' tinha dado certo pela metade.

Duas regras seguram as duas maneiras conhecidas de este modulo mentir sem
quebrar. A primeira: numero que nao foi medido nunca vira zero — abaixo de
`PISO_MBPS` a resposta e' travessao e erro honesto, porque "0,0 Mbps" com badge
verde e' a mentira em que o usuario acredita. A segunda: reabrir conexao tem
piso de volume — resposta 200 sem corpo nao levanta excecao nenhuma, e sem esse
piso o app viraria uma rajada de reconexoes contra o provedor, medindo a propria
velocidade de reconectar.

Cancelar e' um empurrao, nao uma espera. Quem manda parar e' a thread da
interface, entao ela nao pode ficar presa esperando um `read()` voltar: os
sockets sao derrubados pelo descritor, e cada um deles e' registrado desde o
connect — fluxo parado no primeiro byte tambem precisa morrer, senao ele
atravessa a fronteira da fase e consome link durante a medicao seguinte.

Nada aqui depende do Qt. O motor roda em thread propria e quem desenha le
`snapshot()` na cadencia que quiser.
"""
from __future__ import annotations

import io
import os
import random
import socket
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import NamedTuple

from .. import log

_log = log.get("speedtest")


# ── provedores ───────────────────────────────────────────────────────────────
class Provedor(NamedTuple):
    """Um servidor de teste e as manias dele.

    `perto` diz se a casa fica no Brasil (ou num PoP daqui). Serve para saber se
    o numero pode ser lido como a velocidade do link ou se merece ressalva: de
    Ashburn para ca' o RTT sozinho ja' derruba a medida a um quinto do real.

    `cache_buster` decide se a URL leva `?nocache=`. Quando fica em None, a regra
    e' "so' em URL que ja' tem querystring", porque endpoint dinamico foi feito
    para ler parametro e servidor de arquivo estatico nao — o da Hetzner, por
    exemplo, derruba a conexao sem responder quando ve' uma querystring, e era
    exatamente isso que quebrava o servidor reserva de antes.
    """

    url: str
    perto: bool = True
    cache_buster: bool | None = None

    @property
    def host(self) -> str:
        return _host(self.url)

    @property
    def porta(self) -> int:
        return _porta(self.url)

    def pedido(self) -> str:
        """URL desta tentativa — nova a cada reabertura, quando cabe nocache."""
        quer = ("?" in self.url) if self.cache_buster is None else self.cache_buster
        return _sem_cache(self.url) if quer else self.url


PROVEDORES_DOWNLOAD = (
    Provedor("http://speedtest.gru1.linode.com/100MB-gru1.bin"),
    Provedor("https://cachefly.cachefly.net/100mb.test"),
    Provedor("https://speed.cloudflare.com/__down?bytes=90000000"),
    Provedor("https://ash-speed.hetzner.com/100MB.bin", perto=False),
)
"""Fila do download, do melhor para o ultimo recurso.

1. Linode Sao Paulo: 617 Mbps com 4 fluxos e 16 ms. So' em HTTP de proposito —
   o certificado deles nao cobre este hostname, e medir byte nao precisa de TLS.
2. Cachefly: 610 Mbps, 15 ms, anycast de CDN. Empate tecnico com a Linode e, o
   que importa mais numa fila, caminho de rede completamente diferente.
3. Cloudflare: excelente quando nao esta' de castigo. Saiu da frente porque o
   429 por VOLUME castiga justamente quem testa varias vezes — o usuario que
   mais usa o recurso era o que mais via o teste falhar.
4. Hetzner Ashburn: prova de vida internacional. Mede ~72 Mbps num link de
   600, entao entra com `perto=False` e o resultado sai com ressalva. A URL vai
   limpa: com querystring o servidor derruba a conexao sem responder.

Fora da fila de proposito: Vultr SP (HTTP 503 em 2 de 3 tentativas com 4 fluxos
e TTFB de 2,7 s — daria medicao errada com cara de medicao boa) e os espelhos
universitarios, que limitam por conexao e mudam de URL a cada release.
"""

PROVEDORES_UPLOAD = (
    Provedor("https://speed.cloudflare.com/__up"),
    Provedor("http://speedtest.gru1.linode.com/empty.php"),
)
"""Fila do upload. Endpoint que aceita e descarta corpo grande e' raro.

A Cloudflare fica na frente porque mede quase o dobro (441 Mbps contra 192 com
4 fluxos, medido daqui) e porque o corte por volume do __down nao atinge o __up.
Atras dela, o LibreSpeed da Linode em Sao Paulo — o caminho e' `/empty.php`, e
nao `/backend/empty.php`, que devolve 404 nesta instalacao.

Antes desta fila o upload nao tinha plano B nenhum: um tropeco da Cloudflare
apagava o numero inteiro.
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
TENTATIVAS_POR_FLUXO = 3
"""Quantas vezes um fluxo reabre a conexao no MESMO servidor antes de desistir.

Fluxo que morre e nao volta e' o pior defeito possivel aqui: a fase continua
rodando com 3/4 da banda e devolve um numero baixo com cara de medicao boa.
"""
RECUO_S = 0.3
"""Pausa antes de insistir. Voltar na mesma hora transforma tropeco em rajada."""
JOIN_TOTAL_S = 3.0
"""Orcamento SOMADO para encerrar os fluxos da fase, e nao por fluxo."""
PORTA_TLS = 443

PISO_MBPS = 0.05
"""Menor taxa que ainda e' uma MEDIDA, e nao um zero disfarcado.

A tela escreve uma casa decimal: tudo abaixo disto vira "0.0 Mbps" com badge
verde de medicao concluida. Tarpit de anti-abuso, portal cativo, link agonizante
e conexao travada que solta uns bytes depois do aquecimento caem todos nessa
faixa — e "0.0 Mbps" com cara de medicao boa e' pior que erro nenhum, porque o
usuario acredita no numero e vai reclamar da operadora.
"""
BYTES_MINIMOS_POR_ABERTURA = 1 << 20
"""Volume que uma abertura precisa entregar para valer como entrega.

Resposta 200 com corpo vazio (Content-Length: 0, um 204, ou o objeto cortado por
limite de volume — o que a Cloudflare faz) nao levanta excecao nenhuma. Sem este
piso o fluxo reabria na mesma hora, para sempre, e o app virava uma tempestade de
conexoes TCP+TLS contra o provedor: milhoes de aberturas por fase, fabricando
sozinho o HTTP 429 por volume que a fila existe para evitar — e quatro threads em
giro de CPU maxima dentro de um app de MONITORAMENTO contaminam os proprios
numeros da tela. Pior: quando o corpo era minusculo em vez de vazio (pagina de
erro de proxy, portal cativo), os bytes eram contados e o "Mbps" publicado media
a velocidade de RECONEXAO do app, nao a do link.
"""
INTERVALO_MINIMO_ABERTURA_S = 0.02
"""Piso de tempo entre duas aberturas do mesmo fluxo.

Rede de peito aberto: o arquivo de 90 MB dos provedores demora mais de um segundo
por abertura, entao isto nunca morde uma medicao de verdade — so' segura quem
devolve migalha rapido demais.
"""

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

    Devolve None — nunca 0.0 — quando nao houve transferencia ou quando o
    resultado nao alcanca o piso de exibicao. Este era o buraco central do
    modulo: `round(x, 2)` transformava qualquer coisa abaixo de ~625 B/s em
    exatamente 0.0, e esse zero seguia o caminho inteiro (fase pronta, erro
    nenhum, aviso nenhum, badge verde) como se fosse medida limpa. Quem nao
    mediu devolve travessao, e nao zero.
    """
    if segundos <= 0 or transferido <= 0:
        return None
    valor = round(transferido * 8.0 / segundos / 1e6, 2)
    return valor if valor >= PISO_MBPS else None


def _medivel(taxa: float | None) -> bool:
    """Se esta taxa pode virar numero na tela.

    Um so' lugar para a pergunta: quem decide publicar (`_transferir`,
    `_rodar_fila`, `_concluir`) testava `is None` e deixava o 0.0 passar.
    """
    return taxa is not None and taxa >= PISO_MBPS


def taxa_estavel(amostras: list[tuple[float, int]], aquecimento: float = AQUECIMENTO_S,
                 janela_minima: float = JANELA_MINIMA_S) -> float | None:
    """Taxa do trecho ja' aquecido, em Mbps.

    `amostras` sao marcas (instante, bytes acumulados por todos os fluxos). A
    conta usa so' a primeira e a ultima marca uteis: entre elas o total e' exato,
    e qualquer media de fatias intermediarias so' adicionaria ruido de agendamento.

    Quando o teste foi curto demais para sobrar algo depois do aquecimento, vale
    a serie inteira — numero conservador e' melhor que travessao.

    Nada transferido devolve None, e "nada" inclui o byte solto: a guarda em
    bytes (`b1 <= b0`) so' pega o caso exato de zero, e quem barra o resto e' o
    piso de `mbps()` — um unico byte em seis segundos nao e' uma medicao lenta,
    e' uma medicao que nao aconteceu.
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
    """Taxa dos ultimos instantes — e' o numero que corre na tela enquanto mede.

    Vale a mesma regra do numero fechado: sem byte novo na janela nao existe
    parcial. Com `b1 < b0` (e nao `<=`), nenhum byte chegado devolvia 0.0 e o
    tile escrevia "0.0 Mbps · medindo…" durante toda a espera do primeiro byte —
    um numero inventado no lugar do "ainda nao sei".
    """
    if len(amostras) < 2:
        return None
    corte = amostras[-1][0] - janela
    recentes = [a for a in amostras if a[0] >= corte]
    if len(recentes) < 2:
        recentes = amostras[-2:]
    t0, b0 = recentes[0]
    t1, b1 = recentes[-1]
    if t1 <= t0 or b1 <= b0:
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


class RespostaMagra(OSError):
    """O servidor respondeu, aceitou a conexao — e nao entregou dados de medir.

    Corpo vazio, 204, objeto cortado por limite de volume, pagina de portal
    cativo: nada disso levanta excecao, e sem um nome proprio esse caso ou virava
    rajada de reconexao ou virava "0.0 Mbps" com badge verde.
    """


def mensagem_de_erro(exc: BaseException) -> str:
    """Traduz a falha para uma frase que explica o que fazer.

    O usuario nao precisa saber o que e' gaierror; precisa saber se o problema e'
    a internet dele ou o servidor de teste. Numero nenhum aparece junto: zero
    Mbps com cara de medicao e' pior que um erro honesto.

    O 429 tem frase propria porque e' o unico codigo em que a acao certa e'
    ESPERAR. Empacotado no texto generico de "recusou o pedido", ele mandava a
    pessoa investigar o roteador de gracas por um limite que expira sozinho.
    """
    motivo = getattr(exc, "reason", exc)
    if isinstance(exc, RespostaMagra):
        return ("o servidor de teste aceitou a conexão mas não enviou dados; se você "
                "está numa rede pública, pode haver um portal de login no caminho")
    if isinstance(exc, urllib.error.HTTPError):
        if exc.code == 429:
            return ("o servidor de teste pediu para esperar (limite de requisições); "
                    "tente de novo em alguns minutos")
        if exc.code >= 500:
            return f"o servidor de teste está fora do ar no momento (HTTP {exc.code})"
        return f"o servidor de teste recusou o pedido (HTTP {exc.code})"
    if isinstance(motivo, socket.gaierror) or isinstance(exc, socket.gaierror):
        return "sem conexão: não consegui resolver o endereço do servidor de teste"
    if isinstance(motivo, TimeoutError) or isinstance(exc, TimeoutError):
        return "o servidor de teste não respondeu a tempo"
    if isinstance(motivo, ssl.SSLError) or isinstance(exc, ssl.SSLError):
        return ("a conexão segura com o servidor de teste falhou — antivírus ou proxy "
                "da rede pode estar no meio do caminho")
    if isinstance(motivo, ConnectionError) or isinstance(exc, ConnectionError):
        return "a conexão com o servidor de teste caiu no meio do teste"
    if isinstance(motivo, OSError) and getattr(motivo, "strerror", None):
        return f"a rede recusou a conexão ({motivo.strerror})"
    # Ultimo caso: texto de maquina nao vai para a tela nunca. O detalhe fica no
    # log, que e' onde ele ajuda alguem, e nao no card em vermelho.
    _log.debug("falha sem tradução: %r", exc)
    return "não consegui falar com o servidor de teste"


def _peso_do_erro(exc: BaseException) -> int:
    """Quanto uma falha EXPLICA, para escolher qual mostrar.

    Numa fila de servidores (ou de fluxos) sobram varias excecoes, e a que chega
    primeiro costuma ser a menos util. O 429 vem na frente porque diz o que fazer;
    depois os outros codigos HTTP, que ao menos provam que houve resposta; depois
    a resposta vazia, que tambem prova resposta; depois o DNS, que aponta para a
    internet da casa; e por ultimo queda de conexao, que e' o "algo deu errado"
    de sempre.
    """
    if isinstance(exc, urllib.error.HTTPError):
        return 5 if exc.code == 429 else 4
    if isinstance(exc, RespostaMagra):
        return 3
    motivo = getattr(exc, "reason", exc)
    if isinstance(motivo, socket.gaierror) or isinstance(exc, socket.gaierror):
        return 2
    return 1


def _normalizar(falhas) -> list[tuple[str, BaseException, bool]]:
    """Aceita (host, excecao) ou (host, excecao, entregou_bytes)."""
    itens: list[tuple[str, BaseException, bool]] = []
    for falha in falhas:
        host, exc, *resto = falha
        itens.append((host, exc, bool(resto[0]) if resto else False))
    return itens


def _fila_muda(tentados: int, exc: BaseException) -> str:
    """Frase para o caso em que NINGUEM respondeu — o mais mal contado de todos.

    N casas independentes, em redes diferentes, caladas ao mesmo tempo e' a prova
    mais forte que existe de que o problema esta' do lado de ca'. O texto antigo
    juntava essa evidencia e jogava a conclusao fora: "nenhum dos 4 servidores
    respondeu — linode: o servidor de teste nao respondeu a tempo", no singular,
    apontando o dedo justamente para quem nao tem culpa.
    """
    motivo = getattr(exc, "reason", exc)
    if isinstance(motivo, socket.gaierror) or isinstance(exc, socket.gaierror):
        return (f"sem conexão: não consegui nem resolver o endereço de nenhum dos "
                f"{tentados} servidores de teste — confira se a internet está de pé "
                f"(ou se o DNS da rede responde) e tente de novo")
    if isinstance(motivo, TimeoutError) or isinstance(exc, TimeoutError):
        return (f"os {tentados} servidores de teste, em redes independentes, não "
                f"responderam a tempo — quando todos falham juntos o problema costuma "
                f"estar na sua conexão; confira o Wi-Fi ou o cabo e tente de novo")
    return (f"não consegui falar com nenhum dos {tentados} servidores de teste — "
            f"confira a conexão e tente de novo ({mensagem_de_erro(exc)})")


def erro_da_cadeia(falhas, tentados: int) -> str:
    """Uma frase para a fila INTEIRA de servidores — e a conclusao certa dela.

    Guardar so' a ultima falha era o primeiro defeito: com a Cloudflare em 429 e a
    reserva caindo por RemoteDisconnected, o que sobrava na tela era "a conexao
    caiu", e o 429 — a unica informacao acionavel — morria pelo caminho.

    O segundo defeito era a frase unica. "Nenhum dos N servidores respondeu"
    aparecia tambem quando todos responderam 404, quando todos entregaram bytes e
    as transferencias e' que cairam, e quando o proprio 429 provava a resposta. A
    fila existe para separar "o servidor esta' de castigo" de "a internet caiu";
    de nada adianta reunir essa evidencia e escrever sempre a mesma coisa. Cada
    caso tem a frase dele e, junto, o que fazer:

    - respondeu com codigo -> a casa esta' de pe', o pedido e' que foi recusado;
    - entregou bytes e caiu -> a conexao de quem mede esta' derrubando transferencia;
    - aceitou e nao mandou nada -> cheiro de portal cativo ou corte por volume;
    - ninguem respondeu -> a evidencia aponta para a conexao local.
    """
    itens = _normalizar(falhas)
    if not itens:
        return ("o servidor de teste aceitou a conexão mas não entregou dados "
                "suficientes para medir; tente de novo em alguns minutos")
    host, exc, entregou = max(itens, key=lambda f: _peso_do_erro(f[1]))
    frase = mensagem_de_erro(exc)
    if tentados <= 1:
        # Uma casa so' nao prova nada sobre a rede: a frase fica na falha em si.
        return frase
    if isinstance(exc, urllib.error.HTTPError):
        return (f"os {tentados} servidores de teste responderam, mas nenhum aceitou "
                f"medir — {host}: {frase}")
    if isinstance(exc, RespostaMagra):
        return (f"os {tentados} servidores de teste aceitaram a conexão e não enviaram "
                f"dados para medir — se você está numa rede pública, pode haver um "
                f"portal de login no caminho; tente de novo em alguns minutos")
    if entregou or any(e for _, _, e in itens):
        return (f"os {tentados} servidores de teste enviaram dados, mas as "
                f"transferências caíram no meio em todos — o problema está na sua "
                f"conexão, e não neles; confira o Wi-Fi ou o cabo e tente de novo")
    return _fila_muda(tentados, exc)


def _recusa_definitiva(exc: BaseException) -> bool:
    """Erro em que insistir no MESMO endereco so' piora.

    429 e os outros 4xx sao decisao do servidor, nao tropeco de rede: repetir
    gasta tempo da fase e, no caso do limite por volume, ainda ajuda a manter o
    castigo. Nome que nao resolve tambem nao resolve na segunda. Em ambos, o
    caminho certo e' o proximo da fila.
    """
    if isinstance(exc, urllib.error.HTTPError):
        return 400 <= exc.code < 500
    motivo = getattr(exc, "reason", exc)
    return isinstance(motivo, socket.gaierror) or isinstance(exc, socket.gaierror)


def _sem_cache(url: str) -> str:
    """Impede que um proxy no caminho sirva o arquivo do cache dele.

    Cache no meio do caminho nao mede a internet, mede a rede da casa — e o
    numero sai absurdamente alto sem nenhum aviso de que e' mentira.

    Quem decide se isso e' aplicavel e' o Provedor: em servidor de arquivo
    estatico a querystring nao ajuda e as vezes derruba a conexao.
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


class _Medida(NamedTuple):
    """O que uma fase inteira produziu, com as ressalvas junto.

    Trafegar isso em vez de uma taxa solta e' o que permite ao encerramento
    contar a historia certa: qual servidor mediu, se foi preciso descer na fila e
    se algum fluxo ficou pelo caminho.
    """

    taxa: float | None = None
    erro: str | None = None
    provedor: Provedor | None = None
    reserva: bool = False
    degradado: bool = False
    contaminado: bool = False


class _Rodada(NamedTuple):
    """O que UMA tentativa num servidor produziu.

    `entregou` separa "a casa nao respondeu" de "a casa mandou bytes e a
    transferencia caiu" — sem isso a frase final culpa o servidor quando a
    evidencia aponta para a conexao de quem mede.
    """

    taxa: float | None = None
    erros: tuple = ()
    degradado: bool = False
    entregou: bool = False
    contaminado: bool = False


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


class _Trilho:
    """Estado que os fluxos de UMA fase compartilham.

    Junta o contador, o sinal de fim e o registro das quedas. O numero de fluxos
    que desistiram e' tao importante quanto os bytes: fase que terminou com
    metade dos fluxos mortos mediu meia banda, e entregar isso como resultado
    seria mentir baixo — o unico tipo de mentira que o usuario acredita.
    """

    def __init__(self, parar: threading.Event) -> None:
        self.contador = Contador()
        self.fim = threading.Event()
        self.erros: list[BaseException] = []
        self.mortos = 0
        self._parar = parar
        self._lock = threading.Lock()

    def cancelado(self) -> bool:
        return self.fim.is_set() or self._parar.is_set()

    def anotar(self, exc: BaseException) -> None:
        with self._lock:
            self.erros.append(exc)

    def falhas(self) -> tuple:
        """Copia das falhas. Fluxo orfao pode estar anotando enquanto se le."""
        with self._lock:
            return tuple(self.erros)

    def desistiu(self) -> None:
        with self._lock:
            self.mortos += 1

    def esperar(self, segundos: float) -> None:
        """Recuo interrompivel: o fim da fase acorda quem esta' no intervalo."""
        self.fim.wait(segundos)


def _arrebentar(sock) -> None:
    """Derruba o socket no nivel do sistema, sem esperar quem esta' lendo dele.

    Duas chamadas, e as duas sao necessarias:

    - `shutdown()` avisa o outro lado e, no Linux, ja' solta o `recv` pendurado;
    - `_real_close()` fecha o descritor DE VERDADE. No Windows o shutdown nao
      cancela leitura em andamento (medido: o read seguiu preso os 3 s inteiros
      depois de um shutdown bem-sucedido) — so' o `closesocket` derruba. E tem que
      ser o `_real_close`: o `close()` normal apenas marca o objeto como fechado
      enquanto o `makefile()` da resposta segurar uma referencia, que e'
      exatamente o estado em que o socket esta' quando ha' um read em curso.

    Fechar o descritor por baixo de um read em andamento tem um custo conhecido —
    a janela de microssegundos em que aquele numero de descritor pode ser
    reaproveitado. E' o preco de cancelar de verdade: a alternativa era esperar o
    read voltar, e no socket empacado isso e' o timeout inteiro na cara de quem
    clicou em Cancelar.
    """
    if sock is None:
        return
    try:
        sock.shutdown(socket.SHUT_RDWR)
    except (OSError, ValueError):
        pass    # ja' morreu, ainda nao conectou, ou foi destacado pelo TLS
    fechar = getattr(sock, "_real_close", None)
    try:
        (fechar or sock.close)()
    except (OSError, ValueError):
        pass


def _socket_de(objeto):
    """Acha o socket por tras de uma resposta HTTP.

    `HTTPResponse.fp` e' o BufferedReader devolvido por `sock.makefile()`, e o
    socket de verdade mora no `raw._sock` dele.
    """
    if isinstance(objeto, socket.socket):
        return objeto
    for caminho in (("fp", "raw", "_sock"), ("sock",), ("_sock",)):
        alvo = objeto
        for nome in caminho:
            alvo = getattr(alvo, nome, None)
            if alvo is None:
                break
        if isinstance(alvo, socket.socket):
            return alvo
    return None


def _fechar_calado(objeto) -> None:
    try:
        objeto.close()
    except Exception:  # noqa: BLE001 — fechar o que ja' morreu nao e' erro
        pass


def _derrubar(objeto) -> None:
    """Arrebenta uma conexao SEM bloquear quem pediu o cancelamento.

    `HTTPResponse.close()` pega a trava do buffer, e essa trava fica com a thread
    que esta' dentro do `read()` — durante o read INTEIRO. Com o socket empacado
    (link que caiu, VPN que virou, Wi-Fi que sumiu, que e' exatamente quando se
    clica em Cancelar) o close so' voltava no timeout do socket: 10 s congelando
    quem chamou. Como quem chama e' a thread do Qt, o bloqueio nao sumia — apenas
    mudava da thread de trabalho para a da interface, e a janela ia para "Não
    Respondendo". Cancelar tem que ser um empurrao, nao uma espera.
    """
    sock = _socket_de(objeto)
    if sock is not None:
        _arrebentar(sock)
        return
    # Sem socket a vista (duble de teste, transporte exotico): o close pode
    # bloquear, entao vai para uma thread descartavel — nunca na de quem cancelou.
    threading.Thread(target=_fechar_calado, args=(objeto,), daemon=True,
                     name="dbx-fecha").start()


class _Rastreando:
    """Mistura que entrega o socket ao dono assim que ele existe.

    O urllib so' devolve algo palpavel depois de ler o cabecalho da resposta; ate'
    la' — connect, handshake TLS, espera do primeiro byte — nao havia nada para
    cancelar, e um fluxo parado no TTFB era invisivel ao `abortar()`. Ele
    sobrevivia ao fim da fase, atravessava a fronteira e ficava consumindo link no
    meio da medicao seguinte (a fase de upload rodava com quatro downloads ainda
    baixando, e o numero de upload saia baixo sem uma palavra de aviso).

    Trocar a classe de conexao dentro de `do_open` e' o unico ponto de encaixe que
    nao depende do detalhe interno de cada versao do Python: o handler de HTTP e
    o de HTTPS passam por aqui, cada um com os argumentos que ja' passariam.
    """

    def __init__(self, registrar, cancelado=None) -> None:
        super().__init__()
        self._registrar = registrar
        self._cancelado = cancelado

    def do_open(self, http_class, req, **kw):
        return super().do_open(
            _conexao_rastreada(http_class, self._registrar, self._cancelado), req, **kw)


class _HandlerHTTP(_Rastreando, urllib.request.HTTPHandler):
    pass


class _HandlerHTTPS(_Rastreando, urllib.request.HTTPSHandler):
    pass


def _conexao_rastreada(base, registrar, cancelado):
    """Conexao que avisa o dono do socket no momento em que ele nasce."""

    class Conexao(base):
        def connect(self):
            criar = self._create_connection

            def rastreando(*args, **kw):
                s = criar(*args, **kw)
                registrar(s)            # TCP de pe': ja' da' para derrubar
                return s

            self._create_connection = rastreando
            try:
                super().connect()
            finally:
                registrar(getattr(self, "sock", None))   # depois do TLS, o socket e' outro
            if cancelado is not None and cancelado():
                # Cancelou enquanto este socket nascia: o abortar() da fase passou
                # por aqui e nao viu nada. Derruba agora, senao o fluxo ficaria
                # pendurado no primeiro read ate o timeout inteiro.
                _arrebentar(getattr(self, "sock", None))

    return Conexao


class Rede:
    """Transporte HTTP do teste, isolado para o teste automatizado poder trocar."""

    def __init__(self) -> None:
        self._abertos: set = set()
        self._sockets: dict[int, set] = {}
        self._enderecos: dict[tuple[str, int], tuple] = {}
        self._lock = threading.Lock()

    def abortar(self) -> None:
        """Derruba na marra tudo que estiver aberto, sem segurar quem chamou.

        Sem isso o cancelamento so' valeria quando o read() em curso voltasse — e
        num socket travado isso e' o timeout inteiro. Fechar o app no meio de um
        teste deixaria a conexao de pe' esperando dado que ninguem quer mais.

        Volta em microssegundos por construcao: aqui ninguem espera trava de
        buffer nem leitura em andamento — so' se mexe no descritor (`_arrebentar`).
        """
        with self._lock:
            abertos, self._abertos = list(self._abertos), set()
            sockets = [s for grupo in self._sockets.values() for s in grupo]
        for s in sockets:
            _arrebentar(s)
        for objeto in abertos:
            _derrubar(objeto)

    def _registrar_socket(self, sock) -> None:
        """Guarda o socket do fluxo que esta' chamando, para o abortar() achar."""
        if sock is None:
            return
        with self._lock:
            self._sockets.setdefault(threading.get_ident(), set()).add(sock)

    def _soltar_sockets(self) -> None:
        """Fim da transferencia deste fluxo: a lista nao pode virar deposito."""
        with self._lock:
            self._sockets.pop(threading.get_ident(), None)

    def _abrir(self, req: urllib.request.Request, timeout: float, cancelado=None):
        abridor = urllib.request.build_opener(
            _HandlerHTTP(self._registrar_socket, cancelado),
            _HandlerHTTPS(self._registrar_socket, cancelado))
        resp = abridor.open(req, timeout=timeout)
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

        A primeira sonda experimenta TODOS os enderecos do nome e guarda o mais
        rapido; as seguintes vao direto nesse mesmo endereco. Duas razoes:

        - ha' servidor cujo IPv6 esta' publicado mas recusa conexao, e sondar so'
          o primeiro da lista apagava a latencia da tela enquanto o download —
          que tenta todos — ia bem;
        - o resolvedor do Windows devolve os enderecos em ordem rotativa, entao
          "o primeiro da lista" era um host DIFERENTE a cada sonda. As medidas
          alternavam 16 e 38 ms e o jitter saia em 21 ms numa conexao que oscila
          2 — jitter de diversidade de caminho, nao de oscilacao da rede.

        Se o endereco fixado parar de responder, ele e' esquecido e a proxima
        sonda resolve o nome de novo.

        O socket entra na lista de abertos para que `abortar()` possa fecha-lo de
        fora: cancelar durante a latencia nao pode esperar o connect estourar.
        """
        chave = (host, porta)
        with self._lock:
            fixado = self._enderecos.get(chave)
        candidatos = ([fixado] if fixado else
                      [(f, t, p, e)
                       for f, t, p, _, e in socket.getaddrinfo(host, porta,
                                                               type=socket.SOCK_STREAM)])
        melhor: tuple[float, tuple] | None = None
        ultimo: BaseException | None = None
        for alvo in candidatos:
            familia, tipo, proto, endereco = alvo
            s = socket.socket(familia, tipo, proto)
            s.settimeout(timeout)
            with self._lock:
                self._abertos.add(s)
            try:
                inicio = time.perf_counter()
                s.connect(endereco)
                gasto = (time.perf_counter() - inicio) * 1000.0
                if melhor is None or gasto < melhor[0]:
                    melhor = (gasto, alvo)
            except OSError as e:
                ultimo = e
            finally:
                self._fechar(s)
        with self._lock:
            if melhor is None:
                self._enderecos.pop(chave, None)
            else:
                self._enderecos[chave] = melhor[1]
        if melhor is None:
            raise ultimo or OSError(f"sem endereço para {host}")
        return melhor[0]

    def baixar(self, url: str, cancelado, contar, timeout: float) -> None:
        req = urllib.request.Request(url, headers=_CABECALHOS)
        resp = self._abrir(req, timeout, cancelado)
        try:
            while not cancelado():
                bloco = resp.read(BLOCO)
                if not bloco:
                    return
                contar(len(bloco))
        finally:
            self._fechar(resp)
            self._soltar_sockets()

    def enviar(self, url: str, cancelado, contar, timeout: float, tamanho: int) -> None:
        corpo = _CorpoContado(tamanho, contar, cancelado, os.urandom(BLOCO))
        cabecalhos = dict(_CABECALHOS)
        cabecalhos["Content-Type"] = "application/octet-stream"
        cabecalhos["Content-Length"] = str(tamanho)
        req = urllib.request.Request(url, data=corpo, method="POST", headers=cabecalhos)
        resp = self._abrir(req, timeout, cancelado)
        try:
            resp.read(BLOCO)
        finally:
            self._fechar(resp)
            self._soltar_sockets()


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
                 urls_download=PROVEDORES_DOWNLOAD, urls_upload=PROVEDORES_UPLOAD,
                 timeout: float = TIMEOUT_S,
                 tentativas: int = TENTATIVAS_POR_FLUXO) -> None:
        self._rede = rede or Rede()
        self._fluxos = max(1, int(fluxos))
        self._duracao = float(duracao)
        self._aquecimento = float(aquecimento)
        self._janela_minima = float(janela_minima)
        self._sondas = max(1, int(sondas))
        self._download = _fila(urls_download)
        self._upload = _fila(urls_upload)
        self._timeout = float(timeout)
        self._tentativas = max(1, int(tentativas))

        self._lock = threading.Lock()
        self._parar = threading.Event()
        self._thread: threading.Thread | None = None
        self._orfas: list[threading.Thread] = []
        """Fluxos que nao morreram no prazo da fase deles. Ver `_enterrar_orfas`."""
        self._estado = self._zerado()

    # ── estado ───────────────────────────────────────────────────────────────
    def _zerado(self) -> dict:
        return {"fase": FASE_OCIOSO, "rodando": False, "progresso": 0.0,
                "parcial": None, "download": None, "upload": None,
                "ping": None, "jitter": None, "erro": None, "aviso": None,
                "servidor": self._download[0].host if self._download else None,
                "quando": None}

    def _publicar(self, **campos) -> None:
        with self._lock:
            if "progresso" in campos:
                # A barra so' anda para frente. Cada tentativa de servidor
                # reinicia o relogio da fase, e sem esta trava a barra caia de
                # 0,60 para 0,08 ao trocar de provedor — na cara do usuario, no
                # momento em que ele ja' esta' desconfiado da demora.
                anterior = self._estado.get("progresso") or 0.0
                campos["progresso"] = max(anterior, float(campos["progresso"]))
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
        """Espera o teste acabar DE VERDADE — o motor e os fluxos.

        So' o motor era esperado antes, e o `True` saia com quatro fluxos ainda
        segurando socket: quem chamou `stop()` para fechar o app acreditava que
        estava tudo parado enquanto as transferencias seguiam vivas. Prazo
        estourado devolve False, e quem chamou decide o que fazer com isso.
        """
        prazo = time.monotonic() + max(0.0, timeout)
        thread = self._thread
        if thread is not None:
            thread.join(max(0.0, prazo - time.monotonic()))
            if thread.is_alive():
                return False
        for t in self._fluxos_vivos():
            t.join(max(0.0, prazo - time.monotonic()))
        return not self._fluxos_vivos()

    def _fluxos_vivos(self) -> list[threading.Thread]:
        with self._lock:
            self._orfas = [t for t in self._orfas if t.is_alive()]
            return list(self._orfas)

    # ── execucao ─────────────────────────────────────────────────────────────
    def _executar(self) -> None:
        try:
            self._medir_latencia()
            baixado = self._rodar_fila(FASE_DOWNLOAD, self._download)
            enviado = self._rodar_fila(FASE_UPLOAD, self._upload)
            self._concluir(baixado, enviado)
        except Exception as e:  # noqa: BLE001 — thread solta nao pode morrer calada
            _log.warning("teste de velocidade quebrou: %s", e)
            self._publicar(fase=FASE_ERRO, rodando=False, parcial=None,
                           erro=mensagem_de_erro(e), progresso=1.0)
        finally:
            self._publicar(rodando=False, parcial=None)

    def _concluir(self, dl: _Medida, ul: _Medida) -> None:
        if self._parar.is_set():
            self._publicar(fase=FASE_CANCELADO, rodando=False, parcial=None,
                           erro=None, aviso="Teste interrompido.")
            return
        avisos: list[str] = []
        # `_medivel`, e nao `is None`: a taxa que nasce 0.0 nao pode entrar aqui
        # pelo caminho do sucesso, com badge verde e sem uma palavra de ressalva.
        if not _medivel(dl.taxa):
            avisos.append(f"Download ficou de fora — {dl.erro or 'nenhum servidor respondeu'}.")
        else:
            avisos.extend(_ressalvas("Download", dl))
        if not _medivel(ul.taxa):
            avisos.append(f"Upload ficou de fora — {ul.erro or 'nenhum servidor respondeu'}.")
        else:
            avisos.extend(_ressalvas("Upload", ul))

        if not _medivel(dl.taxa) and not _medivel(ul.taxa):
            # Sem nenhuma das duas taxas nao houve teste de velocidade — o ping
            # sozinho nao mede banda —, e ai' e' erro mesmo. A frase precisa
            # dizer que a FILA inteira falhou: "nao respondeu" no singular faz
            # parecer azar de um endereco, e o usuario repete na hora.
            self._publicar(fase=FASE_ERRO, rodando=False, parcial=None, progresso=1.0,
                           erro=dl.erro or ul.erro or "não consegui medir a velocidade",
                           aviso=None)
            return
        # Uma fase que caiu nao apaga a outra: com upload e ping bons, apresentar
        # tudo como fracasso jogava fora dois numeros validos que a tela ja'
        # estava mostrando ao lado da mensagem de erro.
        self._publicar(fase=FASE_PRONTO, rodando=False, parcial=None, progresso=1.0,
                       quando=time.strftime("%H:%M"), erro=None,
                       aviso=" ".join(avisos) if avisos else None)

    # ── latencia ─────────────────────────────────────────────────────────────
    def _medir_latencia(self) -> None:
        """Sonda o primeiro servidor da fila que aceitar conexao.

        Descer na fila importa: se o primeiro estiver fora, o ping ficaria em
        branco mesmo com o download indo bem por outro servidor.
        """
        medidas: list[float] = []
        for prov in self._download:
            for i in range(self._sondas):
                if self._parar.is_set():
                    return
                try:
                    medidas.append(self._rede.sondar(prov.host, prov.porta,
                                                     min(self._timeout, 3.0)))
                except OSError:
                    pass        # sonda perdida vira jitter, nao erro: o download decide
                ms, jitter = latencia(medidas)
                self._publicar(ping=ms, jitter=jitter, servidor=prov.host,
                               progresso=progresso(FASE_LATENCIA, (i + 1) / self._sondas))
                self._parar.wait(0.05)
            if medidas:
                return

    # ── transferencia ────────────────────────────────────────────────────────
    def _rodar_fila(self, fase: str, provedores: tuple[Provedor, ...]) -> _Medida:
        """Percorre os servidores da fase e para no primeiro que medir.

        O resultado e o motivo da falha sao publicados AQUI, e nao so' no
        encerramento: quando o download morre, o usuario passava os 6 s da fase
        de upload olhando um tile vazio e um badge alegre, sem saber que a medida
        ja' tinha acabado em erro.
        """
        if self._parar.is_set():
            return _Medida()
        self._publicar(fase=fase, parcial=None)
        falhas: list[tuple[str, BaseException, bool]] = []
        for indice, prov in enumerate(provedores):
            if self._parar.is_set():
                return _Medida()
            campos = {"parcial": None}
            if fase == FASE_DOWNLOAD:
                # O nome na tela e' o de quem esta' medindo agora, e nao o do
                # primeiro da fila que ja' recusou.
                campos["servidor"] = prov.host
            self._publicar(**campos)

            rodada = self._transferir(fase, prov)
            if _medivel(rodada.taxa):
                # Publicado junto com `parcial=None` num unico update: separar as
                # duas coisas deixava um quadro em que a tela ainda mostrava a
                # parcial cinzenta em cima do valor ja' fechado.
                self._publicar(parcial=None, **{fase: rodada.taxa})   # "download"/"upload"
                return _Medida(rodada.taxa, None, prov, indice > 0, rodada.degradado,
                               rodada.contaminado)
            if rodada.erros:
                falhas.extend((prov.host, e, rodada.entregou) for e in rodada.erros)
            else:
                # Ninguem levantou excecao e mesmo assim nao ha' medida: a casa
                # aceitou a conexao e nao entregou o que medir. Sem este registro
                # a fila terminava sem falha nenhuma e a frase final saia vazia.
                falhas.append((prov.host, RespostaMagra("sem dados para medir"),
                               rodada.entregou))
            if self._parar.is_set():
                return _Medida()
            if indice + 1 < len(provedores):
                self._publicar(aviso=f"não deu para medir em {prov.host}; "
                                     f"tentando {provedores[indice + 1].host}…")

        erro = erro_da_cadeia(falhas, len(provedores))
        _log.info("fase %s sem resultado: %s", fase, erro)
        self._publicar(erro=erro, parcial=None)
        return _Medida(None, erro)

    def _transferir(self, fase: str, prov: Provedor) -> _Rodada:
        """Uma fase inteira num servidor: sobe os fluxos, amostra e fecha tudo."""
        contaminado = self._enterrar_orfas()
        trilho = _Trilho(self._parar)
        threads = [threading.Thread(target=self._fluxo, name=f"speed-{fase}-{i}", daemon=True,
                                    args=(fase, prov, trilho))
                   for i in range(self._fluxos)]
        for t in threads:
            t.start()

        amostras: list[tuple[float, int]] = []
        inicio = time.monotonic()
        try:
            while True:
                agora = time.monotonic()
                decorrido = agora - inicio
                amostras.append((agora, trilho.contador.total))
                if decorrido >= self._duracao or self._parar.is_set():
                    break
                if trilho.mortos >= len(threads) or not any(t.is_alive() for t in threads):
                    break       # todos os fluxos cairam: nao adianta esperar o relogio
                self._publicar(progresso=progresso(fase, decorrido / self._duracao),
                               parcial=taxa_instantanea(amostras))
                self._parar.wait(AMOSTRAGEM_S)
        finally:
            trilho.fim.set()
            self._encerrar_fluxos(threads)

        entregou = trilho.contador.total > 0
        if self._parar.is_set():
            return _Rodada()
        taxa = taxa_estavel(amostras, self._aquecimento, self._janela_minima)
        if _medivel(taxa) and trilho.mortos * 2 >= self._fluxos:
            # Metade dos fluxos morreu: o que sobrou mediu um pedaco da banda e
            # devolveria algo como 150 Mbps num link de 600 — numero baixo com
            # cara de medicao, que e' pior que erro nenhum. Vale mais tentar o
            # proximo servidor da fila.
            _log.info("fase %s em %s: %d de %d fluxos cairam, medida descartada",
                      fase, prov.host, trilho.mortos, self._fluxos)
            taxa = None
        if not _medivel(taxa):
            return _Rodada(None, trilho.falhas(), False, entregou, contaminado)
        return _Rodada(taxa, (), trilho.mortos > 0, True, contaminado)

    # ── fluxos ───────────────────────────────────────────────────────────────
    def _encerrar_fluxos(self, threads: list[threading.Thread]) -> None:
        """Fecha os sockets da fase e espera os fluxos dentro de um orcamento.

        Derrubar as conexoes aqui e' o que faz o encerramento ser imediato: o
        sinal de fim so' e' lido ENTRE dois read(), entao um socket pendurado
        seguraria a fase pelo timeout inteiro.

        O `join` gasta o orcamento SOMADO, e nao 50 ms garantidos por fluxo depois
        do prazo — era assim que a fase seguia em frente com os fluxos vivos. Quem
        nao morreu vira orfa registrada: a proxima fase espera por ela em vez de
        medir com o link ocupado, e `aguardar()` deixa de mentir que acabou.
        """
        self._rede.abortar()
        prazo = time.monotonic() + JOIN_TOTAL_S
        for t in threads:
            t.join(max(0.0, prazo - time.monotonic()))
        vivas = [t for t in threads if t.is_alive()]
        if vivas:
            # Segunda chamada de proposito: o socket de um fluxo que estava no
            # meio do connect pode ter nascido depois da primeira.
            self._rede.abortar()
            for t in vivas:
                t.join(0.05)
            vivas = [t for t in vivas if t.is_alive()]
        if vivas:
            _log.warning("%d fluxo(s) nao encerraram em %.1f s: %s", len(vivas),
                         JOIN_TOTAL_S, ", ".join(t.name for t in vivas))
        with self._lock:
            self._orfas = [t for t in self._orfas + vivas if t.is_alive()]

    def _enterrar_orfas(self) -> bool:
        """Nao comeca uma fase com fluxo da fase anterior ainda no link.

        Fluxo preso dentro do urlopen atravessava a fronteira de fase: a medicao
        de UPLOAD rodava com quatro downloads ainda baixando, e o numero de upload
        saia abaixo do real sem uma palavra de aviso. Aqui a fase espera (com
        orcamento) e, se mesmo assim sobrar alguem, devolve True — o resultado sai
        com ressalva em vez de sair limpo.
        """
        orfas = self._fluxos_vivos()
        if not orfas:
            return False
        _log.info("esperando %d fluxo(s) da fase anterior", len(orfas))
        self._rede.abortar()
        prazo = time.monotonic() + JOIN_TOTAL_S
        for t in orfas:
            t.join(max(0.0, prazo - time.monotonic()))
        return bool(self._fluxos_vivos())

    def _fluxo(self, fase: str, prov: Provedor, trilho: _Trilho) -> None:
        """Um fluxo paralelo: reabre a conexao ate a fase acabar.

        Reabrir e' necessario porque o arquivo do servidor tem tamanho fixo — num
        link rapido ele acaba antes do relogio, e sem a repeticao a segunda metade
        da janela seria medida como zero.

        E reabre tambem depois de ERRO, com recuo, e nao so' depois do fim do
        arquivo: um fluxo que morre no meio e nao volta deixa a fase inteira
        medindo com menos banda do que o link tem. So' desiste de vez quando o
        servidor recusa por decisao propria (4xx, incluindo o 429) ou quando as
        tentativas acabam — e a desistencia fica registrada, porque medida com
        fluxo faltando nao pode passar por medida boa.

        Reabrir tem PISO. O caminho de sucesso nao tinha nenhum: resposta que
        termina sem erro e sem bytes (Content-Length: 0, 204, objeto cortado) fazia
        o laco girar solto — milhoes de aberturas por fase, uma tempestade de
        conexoes contra o provedor e um "Mbps" que media a reconexao do app. Agora
        abertura que nao entrega volume conta como tropeco, com recuo e com
        desistencia registrada, igual a um erro.
        """
        movidos = [0]

        def contar(quantos: int) -> None:
            # Por fluxo, alem do total da fase: o piso de reabertura precisa saber
            # o que ESTA abertura entregou, e nao o que os quatro fluxos somaram.
            movidos[0] += quantos
            trilho.contador.somar(quantos)

        tentativas = 0
        magras = 0
        while not trilho.cancelado():
            antes = movidos[0]
            inicio = time.monotonic()
            try:
                if fase == FASE_DOWNLOAD:
                    self._rede.baixar(prov.pedido(), trilho.cancelado,
                                      contar, self._timeout)
                else:
                    self._rede.enviar(prov.pedido(), trilho.cancelado,
                                      contar, self._timeout, PEDACO_UPLOAD)
            except _Cancelado:
                return
            except Exception as e:  # noqa: BLE001
                if trilho.cancelado():
                    return
                trilho.anotar(e)
                tentativas += 1
                if tentativas >= self._tentativas or _recusa_definitiva(e):
                    trilho.desistiu()
                    return
                trilho.esperar(RECUO_S * tentativas)
                continue
            if movidos[0] - antes >= BYTES_MINIMOS_POR_ABERTURA:
                tentativas = 0      # entregou: o proximo tropeco merece chance nova
                gasto = time.monotonic() - inicio
                if gasto < INTERVALO_MINIMO_ABERTURA_S:
                    trilho.esperar(INTERVALO_MINIMO_ABERTURA_S - gasto)
                continue
            # Terminou sem erro e sem volume. O contador de magras nao zera nunca:
            # alternar "um pedaco bom, um vazio" nao pode virar reabertura infinita.
            magras += 1
            trilho.anotar(RespostaMagra("resposta sem dados para medir"))
            if magras >= self._tentativas:
                trilho.desistiu()
                return
            trilho.esperar(RECUO_S * magras)


def _ressalvas(rotulo: str, medida: _Medida) -> list[str]:
    """O que precisa ser dito sobre um numero que fechou mesmo assim.

    Cair para o segundo servidor da fila deixou de ser motivo de alarme: os
    primeiros da lista estao todos em Sao Paulo e medem igual. O aviso de "pode
    sair abaixo do real" ficou so' para quem esta' fora do pais, que e' o unico
    caso em que a distancia realmente subestima o link.
    """
    fora: list[str] = []
    prov = medida.provedor
    if medida.reserva and prov is not None:
        if prov.perto:
            fora.append(f"{rotulo} medido pelo servidor reserva ({prov.host}).")
        else:
            fora.append(f"{rotulo} medido em {prov.host}, fora do país: "
                        f"o valor sai abaixo do real.")
    if medida.degradado:
        fora.append(f"Parte dos fluxos de {rotulo.lower()} caiu no meio; "
                    f"o valor pode sair abaixo do real.")
    if medida.contaminado:
        # Medir upload com download ainda no ar da' um numero baixo com cara de
        # numero bom. Se nao deu para enterrar a fase anterior a tempo, isso e'
        # dito — calar seria repetir o defeito que a ressalva existe para cobrir.
        fora.append(f"Fluxos da fase anterior ainda estavam no ar durante o "
                    f"{rotulo.lower()}; o valor pode sair abaixo do real.")
    return fora


def _fila(itens) -> tuple[Provedor, ...]:
    """Aceita URLs soltas ou Provedores — string vira Provedor com os padroes."""
    if isinstance(itens, (str, Provedor)):
        itens = (itens,)
    return tuple(i if isinstance(i, Provedor) else Provedor(str(i)) for i in itens)


def _host(url: str) -> str:
    return urllib.parse.urlsplit(url).hostname or url


def _porta(url: str) -> int:
    """Porta do connect da latencia: nem todo servidor de teste fala TLS.

    Fixar 443 sondava uma porta que o servidor podia nem estar ouvindo — a
    latencia sumia da tela por um detalhe que nao tem nada a ver com a rede.
    """
    partes = urllib.parse.urlsplit(url)
    if partes.port:
        return partes.port
    return 80 if partes.scheme == "http" else PORTA_TLS
