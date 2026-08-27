"""Teste de velocidade da conexao, no espirito do Speedtest.

Tres medidas em sequencia (latencia, download e upload) cada uma com varios
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

E a ORDEM dessa fila nao e' mais chutada: antes de medir, todas as casas sao
sondadas em paralelo e a fila e' montada pela latencia observada, como faz o
Ookla. Custa menos de 10 KB e uns dois decimos de segundo (ruido perto do quase
1 GB que o teste move) e e' a diferenca entre medir por um servidor a 16 ms e um
a 134 ms. Empate mantem a ordem da semente, e casa que nao respondeu vai para o
fim da fila em vez de sumir: sonda perdida nao e' prova de servidor morto.

Entre as que responderam, ganha quem tem download E upload no MESMO host. Nao e'
capricho: as duas fases medidas na mesma casa contam a mesma historia, e a tela
para de dizer "via fulano" mostrando um numero de upload que veio de outro lugar.

A lista de servidores tem tres camadas. A semente embutida (Linode, Cachefly,
Cloudflare, Hetzner) e' infraestrutura de nuvem e CDN, com hostname estavel ha'
anos; nunca envelhece como servidor de voluntario. Em cima dela entra a lista
publica do LibreSpeed, guardada em disco com ETag e validade de sete dias e
buscada em SEGUNDO PLANO: o teste de hoje anda com o que ja' esta' no disco e a
busca so' enriquece o de amanha. Medido, a lista publica nao tem uma unica casa
no Brasil (a mais perto e' Atlanta, a 134 ms), entao ela entra como acrescimo e
jamais como substituta da semente: escolher automaticamente dela pioraria o app
em oito vezes. Por cima de tudo, o usuario pode FIXAR um servidor; a escolha fica
gravada e a fila automatica continua atras dela como reserva.

Upload tem um defeito de sistema operacional embutido, e o conserto mora aqui. O
Windows auto-ajusta a janela de RECEPCAO e deixa a de ENVIO cravada em 64 KB,
entao cada fluxo de subida fica limitado a SO_SNDBUF/RTT: 32,8 Mbps por fluxo a
16 ms, 131 Mbps com quatro fluxos, num link que sobe 1 Gbps. Medido nesta
maquina: 118,5 Mbps de upload contra 775 de download, com o MESMO codigo e o
mesmo RTT. Pedir SO_SNDBUF de 4 MB no socket cru, antes do TLS, levou os mesmos
quatro fluxos a mais de 900 Mbps. Aumentar o numero de fluxos tambem "resolveria"
(e' o que o Ookla esconde atras de "Conexoes: Multiplo"), mas so' repete a
janela quebrada mais vezes; o conserto certo e' a janela.

Numero de upload alto merece desconfianca, e o modulo desconfia por conta
propria. Duas contas acompanham a medida: o teto da JANELA (buffer concedido de
verdade pelo sistema x fluxos / RTT) e o teto do PROCESSO (bytes movidos dividido
pelo tempo de CPU que os fluxos gastaram, que e' o que o Python consegue empurrar
com um nucleo). Se o valor medido encostar em qualquer um dos dois, ele deixa de
ser "a velocidade da internet" e passa a ser o teto do app; e a tela diz isso,
com o numero do teto junto. Numero honesto com ressalva vale mais que numero
bonito e falso.

Falha de uma fase nao apaga as outras, e cada numero e' publicado assim que fecha:
o download aparece na tela antes de o upload comecar. O contrario disso, que e'
segurar tudo e no fim virar um "erro" so', joga fora medida boa e faz o usuario
repetir um teste que ja' tinha dado certo pela metade.

Duas regras seguram as duas maneiras conhecidas de este modulo mentir sem
quebrar. A primeira: numero que nao foi medido nunca vira zero: abaixo de
`PISO_MBPS` a resposta e' travessao e erro honesto, porque "0,0 Mbps" com badge
verde e' a mentira em que o usuario acredita. A segunda: reabrir conexao tem
piso de volume: resposta 200 sem corpo nao levanta excecao nenhuma, e sem esse
piso o app viraria uma rajada de reconexoes contra o provedor, medindo a propria
velocidade de reconectar.

Cancelar e' um empurrao, nao uma espera. Quem manda parar e' a thread da
interface, entao ela nao pode ficar presa esperando um `read()` voltar: os
sockets sao derrubados pelo descritor, e cada um deles e' registrado desde o
connect: fluxo parado no primeiro byte tambem precisa morrer, senao ele
atravessa a fronteira da fase e consome link durante a medicao seguinte.

Nada aqui depende do Qt. O motor roda em thread propria e quem desenha le
`snapshot()` na cadencia que quiser.
"""
from __future__ import annotations

import io
import json
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

from .. import log, paths

_log = log.get("speedtest")


class Provedor(NamedTuple):
    """Um servidor de teste e as manias dele.

    `perto` diz se a casa fica no Brasil (ou num PoP daqui). Serve para saber se
    o numero pode ser lido como a velocidade do link ou se merece ressalva: de
    Ashburn para ca' o RTT sozinho ja' derruba a medida a um quinto do real.

    `cache_buster` decide se a URL leva `?nocache=`. Quando fica em None, a regra
    e' "so' em URL que ja' tem querystring", porque endpoint dinamico foi feito
    para ler parametro e servidor de arquivo estatico nao: o da Hetzner, por
    exemplo, derruba a conexao sem responder quando ve' uma querystring, e era
    exatamente isso que quebrava o servidor reserva de antes.

    `envio` e' o endereco de UPLOAD da mesma casa, quando ela tem um. Guardar os
    dois juntos e' o que permite a escolha automatica preferir quem mede as duas
    fases no mesmo lugar; sem isso a tela anunciava "via fulano" com um numero de
    upload que tinha vindo de outro servidor.

    `nome` e' o rotulo humano ("Linode Sao Paulo"); sem ele a tela mostra o
    hostname, que serve mas nao explica onde a casa fica.
    """

    url: str
    perto: bool = True
    cache_buster: bool | None = None
    nome: str = ""
    envio: str = ""

    @property
    def host(self) -> str:
        return _host(self.url)

    @property
    def rotulo(self) -> str:
        return self.nome or self.host

    @property
    def porta(self) -> int:
        return _porta(self.url)

    def pedido(self) -> str:
        """URL desta tentativa, nova a cada reabertura, quando cabe nocache."""
        quer = ("?" in self.url) if self.cache_buster is None else self.cache_buster
        return _sem_cache(self.url) if quer else self.url


def _como_upload(prov: Provedor) -> Provedor:
    """A mesma casa vista pela fase de upload: o endereco de envio vira a URL."""
    return prov._replace(url=prov.envio, envio="")


CANDIDATOS = (
    Provedor("http://speedtest.gru1.linode.com/garbage.php?ckSize=200",
             nome="Linode São Paulo",
             envio="http://speedtest.gru1.linode.com/empty.php"),
    Provedor("https://cachefly.cachefly.net/100mb.test",
             nome="Cachefly (CDN anycast)"),
    Provedor("https://speed.cloudflare.com/__down?bytes=90000000",
             nome="Cloudflare São Paulo",
             envio="https://speed.cloudflare.com/__up"),
    Provedor("https://ash-speed.hetzner.com/100MB.bin", perto=False,
             nome="Hetzner Ashburn (EUA)"),
)
"""Semente embutida: as casas que o app conhece sem perguntar a ninguem.

Esta ordem so' vale quando a sondagem nao conseguir opinar; na vida normal a
fila e' remontada por latencia medida. Ela e' o PISO de qualidade: infraestrutura
de nuvem e CDN, hostname estavel ha' anos, nada de servidor de voluntario que
some no mes seguinte.

1. Linode Sao Paulo: 597 Mbps de descida e 931 de subida, 16 ms. E' um LibreSpeed
   inteiro na RAIZ (`/garbage.php?ckSize=N`, `/empty.php` e `/getIP.php`
   respondem, `/backend/*` da' 404), entao download e upload saem da MESMA casa
   e o tamanho e' sob demanda, sem depender de um arquivo fixo de 100 MB. So' em
   HTTP de proposito: o certificado deles nao cobre este hostname, e medir byte
   nao precisa de TLS.
2. Cachefly: 814 Mbps e 15,3 ms, o melhor download medido; e anycast, ou seja,
   caminho de rede diferente de todos os outros, que e' o que se quer numa fila.
   Nao tem endpoint de upload; serve so' para descer.
3. Cloudflare: 757 de descida e 875 de subida no mesmo host, colo GRU. Fica atras
   porque o 429 por VOLUME castiga justamente quem testa varias vezes. Cuidado
   medido no `bytes=`: 100000000 devolve HTTP 403 e 90000000 responde 200: o
   valor esta' a um passo do precipicio, nao aumente sem testar.
4. Hetzner Ashburn: prova de vida internacional. Mede ~72 Mbps num link de 600,
   entao entra com `perto=False` e o resultado sai com ressalva. A URL vai limpa:
   com querystring o servidor derruba a conexao sem responder.

Fora da semente de proposito: Vultr SP (mede 171 Mbps num link de 900, quatro
vezes abaixo dos outros, medicao errada com cara de medicao boa) e os espelhos
universitarios, que limitam por conexao e mudam de URL a cada release.
"""

PROVEDORES_DOWNLOAD = CANDIDATOS
"""Fila de descida antes da sondagem. Depois dela, quem manda e' a latencia."""

PROVEDORES_UPLOAD = tuple(_como_upload(p) for p in CANDIDATOS if p.envio)
"""Fila do upload. Endpoint que aceita e descarta corpo grande e' raro.

Sai da mesma semente: toda casa que anuncia `envio` entra aqui automaticamente,
entao acrescentar um servidor completo passou a ser uma linha so'. Antes desta
fila o upload nao tinha plano B nenhum: um tropeco da Cloudflare apagava o
numero inteiro.
"""

FLUXOS = 4
"""Fluxos por fase. Quatro bastam DEPOIS do conserto da janela de envio.

Antes dele a taxa era rigorosamente linear no numero de fluxos (1 fluxo 29 Mbps,
4 fluxos 119, 16 fluxos 463, sempre 24-29 Mbps por fluxo), e essa linearidade e'
a assinatura de limite POR CONEXAO, nao de link cheio. Subir para 16 conexoes
"resolveria" o numero sem consertar nada, ao custo de uma rajada contra o
provedor: e' o que o Ookla esconde atras de "Conexoes: Multiplo". Com SO_SNDBUF
corrigido, um fluxo sozinho ja' faz 385-533 Mbps e quatro passam de 900.
"""
DURACAO_S = 6.0
"""Duracao de cada fase. NAO encurte junto com o aumento do SO_SNDBUF.

Com 4 MB por fluxo ficam ate' 16 MB entregues ao socket que o servidor ainda nao
confirmou. Em regime isso e' um offset constante e cancela na subtracao das duas
marcas (medido: +0,3% de erro na janela usada aqui), mas numa janela de 0,5 s o
mesmo excesso passa a mentir +323%. Quem encurtar isto sem encurtar o buffer faz
o upload marcar quatro vezes acima do real; e o app tem uma ressalva propria
para delatar exatamente esse caso, ver `FOLGA_DE_BUFFER`.
"""
AQUECIMENTO_S = 1.5
"""Tempo descartado no inicio de cada fase (slow start do TCP).

Folgado de proposito: o slow start acaba em ~300 ms com RTT de 16 ms, entao 1,5 s
e' cinco vezes o necessario. A folga aqui e' o que garante que a medicao comece
com o buffer de envio ja' cheio, que e' a condicao para o excesso contado virar
offset constante e cancelar.
"""
JANELA_MINIMA_S = 0.5
"""Abaixo disso a divisao vira ruido, nao medida."""
AMOSTRAGEM_S = 0.1
SONDAS = 6
TIMEOUT_S = 10.0
BLOCO = 1 << 16
PEDACO_UPLOAD = 60_000_000
"""Corpo prometido em cada POST.

Generoso de proposito: sobrar nao custa nada (a fase acaba e o envio e' abortado
no meio), mas faltar custa um handshake TLS novo a cada pedaco: num link de
upload rapido esse vaivem apareceria como buraco na medicao.

Este valor foi confirmado com o buffer ja' corrigido: e' a configuracao em que a
Linode mediu 931,8 Mbps e a Cloudflare 874,8. Aumentar parece tentador (menos
reaberturas ainda) mas e' aposta: nao ha' medida de como cada endpoint reage a um
Content-Length muito maior, e um 413 aqui apaga o upload inteiro.
"""
SNDBUF_UPLOAD = 4 << 20
"""Buffer de ENVIO pedido ao sistema, em bytes, so' na fase de upload.

O Windows entrega 65536 e nao mexe mais nisso; o teto por fluxo vira SNDBUF/RTT,
e nao a banda do link. A 16 ms de RTT isso da' 32,8 Mbps por fluxo, com quatro
fluxos, os 118,5 Mbps que este modulo media num link que sobe 1 Gbps. A janela
deixa de morder quando o buffer passa de `taxa_do_link x RTT / fluxos`, que aqui
e' 519 KB; 4 MB da' folga de oito vezes e some com o gargalo. Medido: 1 fluxo com
256 KB foi de 29 para 110 Mbps, e 4 fluxos com 4 MB passaram de 900.

No download nao adianta nada: a janela de RECEPCAO o Windows ja' auto-ajusta
sozinho (379 KB em voo por fluxo, medidos), e e' exatamente por isso que o mesmo
codigo baixava a 775 Mbps e subia a 118.
"""
TETO_DUVIDA = 0.85
"""Fracao do teto a partir da qual o numero deixa de falar sobre a internet.

Encostar no teto da janela ou no teto de CPU do processo significa que o que foi
medido e' o app, e nao o link. Abaixo disso o teto nao morde e nao ha' nada a
dizer; a partir dai' a tela diz qual teto e' e quanto ele vale.
"""
FOLGA_DE_BUFFER = 0.2
"""Quanto de buffer nao entregue ainda cabe dentro de uma janela de medicao.

O contador soma o que foi entregue ao SOCKET, nao o que o servidor confirmou.
Isso erra para CIMA, e o erro cancela: em regime a ocupacao do buffer e' um
offset constante e a conta usa a diferenca entre duas marcas. O que nao cancela
e' janela curta: com 4 MB por fluxo, medidos, uma janela de 0,5 s passa a mentir
+323%. Entao quando `fluxos x buffer` chega perto do volume da janela, o numero
sai com ressalva em vez de sair limpo.
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

SONDAS_DA_ESCOLHA = 2
"""Connects por candidato na varredura. Vale o MINIMO, e minimo de duas amostras
ja' separa 15 ms de 134 ms, que e' a unica pergunta desta fase."""
TRABALHADORES_SONDA = 16
"""Sondas em paralelo. Latencia e' barata: 22 casas com 4 connects cada sairam em
poucos segundos e menos de 10 KB somados, ruido perto do ~1 GB que o teste move."""
PRAZO_DA_ESCOLHA_S = 2.5
"""Teto de relogio da varredura inteira. Estourou, decide com o que ja' chegou."""
FILA_MAXIMA = 4
"""Quantos servidores entram na fila de uma fase depois da escolha.

Sem teto, uma lista publica de 22 casas viraria 22 tentativas de 6 s cada num dia
ruim. Quatro casas independentes ja' provam o que a fila existe para provar.
"""
CANDIDATOS_MAXIMOS = 24
"""Teto de casas sondadas. A varredura e' barata, mas nao e' de graca."""

LISTA_URL = "https://librespeed.org/backend-servers/servers.json"
"""Lista publica do LibreSpeed. Medida: 6.115 bytes, uma requisicao, 22 casas;
e NENHUMA no Brasil (a mais perto e' Atlanta, a 134,1 ms). Por isso ela enriquece
a semente e nunca a substitui: escolher automaticamente dela daria um servidor
oito vezes pior do que o que o app ja' tem embutido."""
LISTA_TTL_S = 7 * 24 * 3600
"""Validade do cache. A lista muda em meses, nao em minutos."""
LISTA_TIMEOUT_S = 3.0
LISTA_MAX_BYTES = 1 << 20
"""Teto de leitura da lista. Sem isso, um endereco sequestrado poderia empurrar
um arquivo infinito para dentro de um app de monitoramento."""
ARQUIVO_ESTADO = "speedtest.json"
"""Servidor fixado pelo usuario e cache da lista publica, no mesmo lugar."""

PISO_MBPS = 0.05
"""Menor taxa que ainda e' uma MEDIDA, e nao um zero disfarcado.

A tela escreve uma casa decimal: tudo abaixo disto vira "0.0 Mbps" com badge
verde de medicao concluida. Tarpit de anti-abuso, portal cativo, link agonizante
e conexao travada que solta uns bytes depois do aquecimento caem todos nessa
faixa; e "0.0 Mbps" com cara de medicao boa e' pior que erro nenhum, porque o
usuario acredita no numero e vai reclamar da operadora.
"""
BYTES_MINIMOS_POR_ABERTURA = 1 << 20
"""Volume que uma abertura precisa entregar para valer como entrega.

Resposta 200 com corpo vazio (Content-Length: 0, um 204, ou o objeto cortado por
limite de volume, o que a Cloudflare faz) nao levanta excecao nenhuma. Sem este
piso o fluxo reabria na mesma hora, para sempre, e o app virava uma tempestade de
conexoes TCP+TLS contra o provedor: milhoes de aberturas por fase, fabricando
sozinho o HTTP 429 por volume que a fila existe para evitar; e quatro threads em
giro de CPU maxima dentro de um app de MONITORAMENTO contaminam os proprios
numeros da tela. Pior: quando o corpo era minusculo em vez de vazio (pagina de
erro de proxy, portal cativo), os bytes eram contados e o "Mbps" publicado media
a velocidade de RECONEXAO do app, nao a do link.
"""
INTERVALO_MINIMO_ABERTURA_S = 0.02
"""Piso de tempo entre duas aberturas do mesmo fluxo.

Rede de peito aberto: o arquivo de 90 MB dos provedores demora mais de um segundo
por abertura, entao isto nunca morde uma medicao de verdade; so' segura quem
devolve migalha rapido demais.
"""

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

_CABECALHOS = {"User-Agent": "DbxStats/3.0", "Cache-Control": "no-cache",
               "Pragma": "no-cache"}


def mbps(transferido: float, segundos: float) -> float | None:
    """Megabits por segundo, a unidade em que a operadora vende o plano.

    Byte vira bit e o divisor e' 1e6, nao 2^20: comparar com "300 mega" da conta
    de luz da internet so' faz sentido na escala decimal.

    Devolve None (nunca 0.0) quando nao houve transferencia ou quando o
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


def janela_util(amostras: list[tuple[float, int]], aquecimento: float = AQUECIMENTO_S,
                janela_minima: float = JANELA_MINIMA_S) -> tuple[float, int] | None:
    """(segundos, bytes) do trecho ja' aquecido, o pedaco que vale medir.

    A conta usa so' a primeira e a ultima marca uteis: entre elas o total e'
    exato, e qualquer media de fatias intermediarias so' adicionaria ruido de
    agendamento.

    Quando o teste foi curto demais para sobrar algo depois do aquecimento, vale
    a serie inteira: numero conservador e' melhor que travessao.

    Existe separada de `taxa_estavel` porque o VOLUME da janela responde a outra
    pergunta, tao importante quanto a taxa: se o que foi transferido cabe dentro
    do buffer de envio, o numero e' enchimento de buffer, e nao medida.
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
    return t1 - t0, b1 - b0


def taxa_estavel(amostras: list[tuple[float, int]], aquecimento: float = AQUECIMENTO_S,
                 janela_minima: float = JANELA_MINIMA_S) -> float | None:
    """Taxa do trecho ja' aquecido, em Mbps.

    `amostras` sao marcas (instante, bytes acumulados por todos os fluxos).

    Nada transferido devolve None, e "nada" inclui o byte solto: a guarda em
    bytes (`b1 <= b0`) so' pega o caso exato de zero, e quem barra o resto e' o
    piso de `mbps()`: um unico byte em seis segundos nao e' uma medicao lenta,
    e' uma medicao que nao aconteceu.
    """
    janela = janela_util(amostras, aquecimento, janela_minima)
    if janela is None:
        return None
    segundos, bytes_ = janela
    return mbps(bytes_, segundos)


def teto_da_janela(sndbuf: int, ping_ms: float | None, fluxos: int) -> float | None:
    """Teto de subida imposto pela janela de ENVIO, em Mbps.

    `buffer x 8 x fluxos / RTT`: enquanto o outro lado nao confirma, o fluxo nao
    pode ter mais que um buffer em voo, entao o buffer dividido pela ida e volta
    e' um teto duro, independente da banda contratada.

    Com o buffer padrao do Windows (65536) e 16 ms isso da' 131 Mbps para quatro
    fluxos, que era exatamente o que este modulo media. Serve para duas coisas:
    dizer na tela quanto vale o teto e delatar o dia em que o `setsockopt` nao
    pegar: porque ai' o numero volta a ser baixo, e calado.
    """
    if not sndbuf or not ping_ms or ping_ms <= 0 or fluxos <= 0:
        return None
    return mbps(sndbuf * fluxos, ping_ms / 1000.0)


def teto_do_processo(bytes_movidos: int, cpu_s: float) -> float | None:
    """Quanto este processo consegue empurrar com UM nucleo, em Mbps.

    Nao e' estimativa: sao os bytes que os fluxos moveram divididos pelo tempo de
    CPU que essas mesmas threads gastaram para move-los. Como o interpretador so'
    executa bytecode de uma thread por vez, "um nucleo" e' o teto natural do
    caminho em Python: o que roda dentro do OpenSSL e do kernel de fato escapa
    da trava, entao o numero e' CONSERVADOR: o teto real e' um pouco maior.

    Medido nesta maquina: 0,59 s de CPU por GB com blocos de 64 KB (~13 Gbps) e
    3,01 s por GB com blocos de 8 KB (~2,7 Gbps), cinco vezes mais caro pelo
    mesmo resultado, e num app de MONITORAMENTO essa CPU contamina os proprios
    numeros da tela. Dai' o bloco de 64 KB na conexao de upload.
    """
    if bytes_movidos <= 0 or cpu_s <= 0:
        return None
    return mbps(bytes_movidos, cpu_s)


def taxa_instantanea(amostras: list[tuple[float, int]], janela: float = 1.0) -> float | None:
    """Taxa dos ultimos instantes: e' o numero que corre na tela enquanto mede.

    Vale a mesma regra do numero fechado: sem byte novo na janela nao existe
    parcial. Com `b1 < b0` (e nao `<=`), nenhum byte chegado devolvia 0.0 e o
    tile escrevia "0.0 Mbps · medindo…" durante toda a espera do primeiro byte,
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
    16 ms, acontece o tempo todo) puxava a media para 10 ms e pintava de instavel
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


_disco = threading.Lock()


def _arquivo_estado():
    return paths.data_dir() / ARQUIVO_ESTADO


def ler_estado() -> dict:
    """Preferencia e cache gravados. Arquivo ausente ou corrompido = sem estado.

    Nunca levanta: um JSON truncado por queda de energia nao pode impedir o app de
    medir a internet.
    """
    try:
        with open(_arquivo_estado(), encoding="utf-8") as f:
            dados = json.load(f)
    except (OSError, ValueError):
        return {}
    return dados if isinstance(dados, dict) else {}


def gravar_estado(mudanca: dict) -> None:
    """Atualiza as chaves dadas preservando o resto, e troca o arquivo inteiro.

    O `os.replace` e' o que impede o caso classico: o app fechado no meio da
    escrita deixando um arquivo pela metade que na proxima abertura seria lido
    como "sem servidor fixado".
    """
    with _disco:
        dados = ler_estado()
        dados.update(mudanca)
        alvo = _arquivo_estado()
        temporario = alvo.with_name(alvo.name + ".tmp")
        try:
            with open(temporario, "w", encoding="utf-8") as f:
                json.dump(dados, f)
            os.replace(temporario, alvo)
        except OSError as e:
            _log.debug("não deu para gravar %s: %s", ARQUIVO_ESTADO, e)


def servidor_fixado() -> str | None:
    """Host que o usuario mandou usar, se mandou algum."""
    valor = ler_estado().get("fixado")
    return valor or None


def fixar_servidor(host: str | None) -> None:
    """Fixa (ou solta) o servidor. Fixar nao apaga a fila: ela fica de reserva."""
    gravar_estado({"fixado": host or ""})


def _absoluta(base: str, caminho: str) -> str:
    """Junta `server` + `dlURL` do formato LibreSpeed.

    Dois detalhes medidos na lista real: o campo `server` as vezes vem sem
    esquema ("//host/path") e precisa ser normalizado, e o caminho pode ser na
    raiz ou em /backend conforme a instalacao: por isso a juncao e' relativa ao
    que o proprio servidor declarou, e nao um caminho chutado por nos.
    """
    base = base.strip()
    if base.startswith("//"):
        base = "https:" + base
    if not base.endswith("/"):
        base += "/"
    return urllib.parse.urljoin(base, caminho.strip().lstrip("/"))


def provedores_da_lista(itens) -> tuple[Provedor, ...]:
    """Converte a lista publica do LibreSpeed em provedores deste modulo.

    Entrada malformada e' descartada em silencio, nao propagada: a lista vem da
    internet e nao ha' nada que possa ser feito com um item quebrado alem de
    ignora-lo. Tudo que vem de fora entra com `perto=False`: nao ha' um campo
    confiavel de pais na lista, e prometer proximidade que nao existe seria
    justamente o tipo de mentira que este modulo combate.
    """
    saida: list[Provedor] = []
    for item in itens if isinstance(itens, list) else ():
        if not isinstance(item, dict):
            continue
        base = str(item.get("server") or "")
        descida = str(item.get("dlURL") or "")
        if not base or not descida:
            continue
        try:
            url = _absoluta(base, descida)
            subida = _absoluta(base, str(item["ulURL"])) if item.get("ulURL") else ""
        except ValueError:
            continue
        if not _host(url):
            continue
        saida.append(Provedor(url, perto=False, nome=str(item.get("name") or _host(url)),
                              envio=subida))
    return tuple(saida)


def lista_em_cache() -> tuple[Provedor, ...]:
    """A lista publica como ela esta' no disco AGORA, sem tocar na rede.

    O teste de hoje nunca espera a lista: ele anda com o que ja' foi guardado, e a
    busca em segundo plano so' enriquece o de amanha. Sem essa regra, um servidor
    de lista lento seguraria a fase de latencia inteira para acrescentar
    candidatos que, medidos, ficam a 134 ms, ou seja, para piorar.
    """
    return provedores_da_lista(ler_estado().get("lista") or [])


def lista_vencida(agora: float | None = None) -> bool:
    """Se vale a pena perguntar a lista de novo. Sete dias e' a idade dela."""
    estado = ler_estado()
    if not estado.get("lista"):
        return True
    quando = float(estado.get("lista_quando") or 0.0)
    return (time.time() if agora is None else agora) - quando >= LISTA_TTL_S


def atualizar_lista(rede, url: str = LISTA_URL, timeout: float = LISTA_TIMEOUT_S,
                    agora: float | None = None) -> int:
    """Busca a lista publica e guarda no disco. Devolve quantas casas vieram.

    Custo medido: 6.115 bytes na resposta cheia e ~300 bytes quando o ETag bate e
    o servidor responde 304. Falha nao e' erro: sem lista o app mede com a semente
    embutida, que e' o que ele ja' fazia antes de existir lista nenhuma.
    """
    agora = time.time() if agora is None else agora
    if not lista_vencida(agora):
        return 0
    estado = ler_estado()
    try:
        codigo, corpo, etag = rede.texto(url, timeout, estado.get("lista_etag"))
    except Exception as e:  # noqa: BLE001: lista e' bonus, nunca motivo de falha
        _log.debug("lista pública não veio: %s", e)
        return 0
    if codigo == 304:
        # Nada mudou: renova a validade sem reescrever a lista.
        gravar_estado({"lista_quando": agora})
        return 0
    try:
        itens = json.loads(corpo)
    except ValueError:
        _log.debug("lista pública veio em formato desconhecido")
        return 0
    if not isinstance(itens, list) or not itens:
        return 0
    itens = [i for i in itens if isinstance(i, dict)][:CANDIDATOS_MAXIMOS]
    gravar_estado({"lista": itens, "lista_quando": agora, "lista_etag": etag or ""})
    return len(itens)


class Escolha(NamedTuple):
    """Quem vai medir, quanto ele custou de latencia e quem fica de reserva."""

    servidor: Provedor | None = None
    download: tuple[Provedor, ...] = ()
    upload: tuple[Provedor, ...] = ()
    latencia_ms: float | None = None
    sondados: int = 0
    responderam: int = 0
    fixado: bool = False


def _sem_repetir(provedores) -> tuple[Provedor, ...]:
    """Um provedor por host: sondar a mesma casa duas vezes so' gasta relogio."""
    vistos: set[str] = set()
    saida: list[Provedor] = []
    for p in provedores:
        if p.host and p.host not in vistos:
            vistos.add(p.host)
            saida.append(p)
    return tuple(saida)


def _por_latencia(provedores, latencias: dict):
    """Ordena pela ida e volta medida, com quem nao respondeu no fim.

    `sorted` e' estavel, entao empate (inclusive o empate de todo mundo mudo)
    preserva a ordem da semente. Quem nao respondeu NAO e' descartado: sonda
    perdida pode ser um pacote azarado, e uma fila vazia mede menos que uma fila
    duvidosa.
    """
    def chave(p: Provedor):
        ms = latencias.get(p.host)
        return (1, 0.0) if ms is None else (0, ms)

    return sorted(provedores, key=chave)


def _puxar(fila: list, host: str) -> list:
    """Traz o host escolhido para a frente sem perder o resto da fila."""
    frente = [p for p in fila if p.host == host]
    return frente + [p for p in fila if p.host != host] if frente else fila


def escolher(download, upload, latencias: dict, fixado: str | None = None,
             limite: int = FILA_MAXIMA) -> Escolha:
    """Monta as filas das duas fases a partir das latencias medidas.

    A regra, nesta ordem:

    1. servidor fixado pelo usuario, se ele fixou um: vontade declarada ganha de
       medicao, sempre; a fila automatica continua atras, como reserva;
    2. entre os que responderam, quem tem download E upload no mesmo host;
    3. entre esses, a menor latencia;
    4. os proximos ficam de reserva, e quem nao respondeu vai para o fim.

    O item 2 vem antes do 3 de proposito, e custa pouco: aqui os finalistas
    ficaram todos entre 15,3 e 16,7 ms, ou seja, a latencia ordena mas nao
    distingue. O que ela NAO faz e' prever vazao (171 a 814 Mbps na mesma faixa de
    latencia), e por isso a reserva importa: se o escolhido medir muito abaixo do
    esperado, a fila desce sozinha.
    """
    dl = _por_latencia(_sem_repetir(download), latencias)
    ul = _por_latencia(_sem_repetir(upload), latencias)
    completos = {p.host for p in ul}
    vivos = [p for p in dl if latencias.get(p.host) is not None]
    servidor = next((p for p in vivos if p.host in completos), None)
    if servidor is None:
        servidor = vivos[0] if vivos else (dl[0] if dl else None)
    marcado = False
    if fixado:
        preferido = next((p for p in dl + ul if p.host == fixado), None)
        if preferido is not None:
            servidor, marcado = preferido, True
    if servidor is not None:
        dl = _puxar(dl, servidor.host)
        ul = _puxar(ul, servidor.host)
    return Escolha(servidor, tuple(dl[:limite]), tuple(ul[:limite]),
                   latencias.get(servidor.host) if servidor else None,
                   len(latencias), sum(1 for v in latencias.values() if v is not None),
                   marcado)


class RespostaMagra(OSError):
    """O servidor respondeu, aceitou a conexao; e nao entregou dados de medir.

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
        return ("a conexão segura com o servidor de teste falhou: antivírus ou proxy "
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
    """Frase para o caso em que NINGUEM respondeu, o mais mal contado de todos.

    N casas independentes, em redes diferentes, caladas ao mesmo tempo e' a prova
    mais forte que existe de que o problema esta' do lado de ca'. O texto antigo
    juntava essa evidencia e jogava a conclusao fora: "nenhum dos 4 servidores
    respondeu, linode: o servidor de teste nao respondeu a tempo", no singular,
    apontando o dedo justamente para quem nao tem culpa.
    """
    motivo = getattr(exc, "reason", exc)
    if isinstance(motivo, socket.gaierror) or isinstance(exc, socket.gaierror):
        return (f"sem conexão: não consegui nem resolver o endereço de nenhum dos "
                f"{tentados} servidores de teste: confira se a internet está de pé "
                f"(ou se o DNS da rede responde) e tente de novo")
    if isinstance(motivo, TimeoutError) or isinstance(exc, TimeoutError):
        return (f"os {tentados} servidores de teste, em redes independentes, não "
                f"responderam a tempo: quando todos falham juntos o problema costuma "
                f"estar na sua conexão; confira o Wi-Fi ou o cabo e tente de novo")
    return (f"não consegui falar com nenhum dos {tentados} servidores de teste; "
            f"confira a conexão e tente de novo ({mensagem_de_erro(exc)})")


def erro_da_cadeia(falhas, tentados: int) -> str:
    """Uma frase para a fila INTEIRA de servidores; e a conclusao certa dela.

    Guardar so' a ultima falha era o primeiro defeito: com a Cloudflare em 429 e a
    reserva caindo por RemoteDisconnected, o que sobrava na tela era "a conexao
    caiu", e o 429 (a unica informacao acionavel) morria pelo caminho.

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
                f"medir, {host}: {frase}")
    if isinstance(exc, RespostaMagra):
        return (f"os {tentados} servidores de teste aceitaram a conexão e não enviaram "
                f"dados para medir: se você está numa rede pública, pode haver um "
                f"portal de login no caminho; tente de novo em alguns minutos")
    if entregou or any(e for _, _, e in itens):
        return (f"os {tentados} servidores de teste enviaram dados, mas as "
                f"transferências caíram no meio em todos: o problema está na sua "
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

    Cache no meio do caminho nao mede a internet, mede a rede da casa; e o
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
    teto_processo: float | None = None
    """Quanto o app consegue empurrar com um nucleo, medido nesta fase."""
    teto_janela: float | None = None
    """Teto imposto pelo buffer de envio concedido e pelo RTT."""
    inflado: bool = False
    """A janela de medicao foi curta demais para o tamanho do buffer de envio."""


class _Rodada(NamedTuple):
    """O que UMA tentativa num servidor produziu.

    `entregou` separa "a casa nao respondeu" de "a casa mandou bytes e a
    transferencia caiu": sem isso a frase final culpa o servidor quando a
    evidencia aponta para a conexao de quem mede.
    """

    taxa: float | None = None
    erros: tuple = ()
    degradado: bool = False
    entregou: bool = False
    contaminado: bool = False
    teto_processo: float | None = None
    teto_janela: float | None = None
    inflado: bool = False


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
    seria mentir baixo, o unico tipo de mentira que o usuario acredita.
    """

    def __init__(self, parar: threading.Event) -> None:
        self.contador = Contador()
        self.fim = threading.Event()
        self.erros: list[BaseException] = []
        self.mortos = 0
        self.cpu = 0.0
        """Tempo de CPU somado das threads de fluxo, o teto do processo sai daqui."""
        self._parar = parar
        self._lock = threading.Lock()

    def gastar_cpu(self, segundos: float) -> None:
        if segundos > 0:
            with self._lock:
                self.cpu += segundos

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
      depois de um shutdown bem-sucedido); so' o `closesocket` derruba. E tem que
      ser o `_real_close`: o `close()` normal apenas marca o objeto como fechado
      enquanto o `makefile()` da resposta segurar uma referencia, que e'
      exatamente o estado em que o socket esta' quando ha' um read em curso.

    Fechar o descritor por baixo de um read em andamento tem um custo conhecido:
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
    except Exception:  # noqa: BLE001: fechar o que ja' morreu nao e' erro
        pass


def _derrubar(objeto) -> None:
    """Arrebenta uma conexao SEM bloquear quem pediu o cancelamento.

    `HTTPResponse.close()` pega a trava do buffer, e essa trava fica com a thread
    que esta' dentro do `read()`, durante o read INTEIRO. Com o socket empacado
    (link que caiu, VPN que virou, Wi-Fi que sumiu, que e' exatamente quando se
    clica em Cancelar) o close so' voltava no timeout do socket: 10 s congelando
    quem chamou. Como quem chama e' a thread do Qt, o bloqueio nao sumia; apenas
    mudava da thread de trabalho para a da interface, e a janela ia para "Não
    Respondendo". Cancelar tem que ser um empurrao, nao uma espera.
    """
    sock = _socket_de(objeto)
    if sock is not None:
        _arrebentar(sock)
        return
    # Sem socket a vista (duble de teste, transporte exotico): o close pode
    # bloquear, entao vai para uma thread descartavel, nunca na de quem cancelou.
    threading.Thread(target=_fechar_calado, args=(objeto,), daemon=True,
                     name="dbx-fecha").start()


def pedir_buffer_de_envio(sock, tamanho: int) -> int:
    """Pede um buffer de envio maior e devolve o que o sistema concedeu.

    O `min` com o pedido nao e' desconfianca: o Linux devolve o DOBRO do que foi
    pedido (ele conta a contabilidade interna junto), e usar esse numero dobrado
    na conta do teto faria o app achar que tem o triplo da folga que tem. Quando
    o sistema concede menos que o pedido (limite administrativo) o valor de
    volta e' o verdadeiro, e e' ele que interessa.

    Falhar aqui nao e' motivo para abortar nada: sem o buffer maior o upload
    volta a ser o de antes, baixo, e quem denuncia isso e' o teto da janela na
    tela, em vez de o numero sair baixo e calado.
    """
    if sock is None or tamanho <= 0:
        return 0
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, int(tamanho))
        return min(int(sock.getsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF)), int(tamanho))
    except OSError as e:
        _log.debug("SO_SNDBUF recusado: %s", e)
        return 0


class _Rastreando:
    """Mistura que entrega o socket ao dono assim que ele existe.

    O urllib so' devolve algo palpavel depois de ler o cabecalho da resposta; ate'
    la' (connect, handshake TLS, espera do primeiro byte) nao havia nada para
    cancelar, e um fluxo parado no TTFB era invisivel ao `abortar()`. Ele
    sobrevivia ao fim da fase, atravessava a fronteira e ficava consumindo link no
    meio da medicao seguinte (a fase de upload rodava com quatro downloads ainda
    baixando, e o numero de upload saia baixo sem uma palavra de aviso).

    Trocar a classe de conexao dentro de `do_open` e' o unico ponto de encaixe que
    nao depende do detalhe interno de cada versao do Python: o handler de HTTP e
    o de HTTPS passam por aqui, cada um com os argumentos que ja' passariam.
    """

    def __init__(self, registrar, cancelado=None, sndbuf: int = 0, anotar_buffer=None) -> None:
        super().__init__()
        self._registrar = registrar
        self._cancelado = cancelado
        self._sndbuf = sndbuf
        self._anotar_buffer = anotar_buffer

    def do_open(self, http_class, req, **kw):
        return super().do_open(
            _conexao_rastreada(http_class, self._registrar, self._cancelado,
                               self._sndbuf, self._anotar_buffer), req, **kw)


class _HandlerHTTP(_Rastreando, urllib.request.HTTPHandler):
    pass


class _HandlerHTTPS(_Rastreando, urllib.request.HTTPSHandler):
    pass


def _conexao_rastreada(base, registrar, cancelado, sndbuf: int = 0, anotar_buffer=None):
    """Conexao que avisa o dono do socket no momento em que ele nasce.

    E' tambem o unico ponto do caminho em que o socket ainda esta' CRU: depois do
    handshake o objeto que sobra e' o SSLSocket, e pedir buffer de envio ali ja'
    seria tarde para a fase de subida. Por isso o `setsockopt` mora dentro de
    `rastreando()`, colado no `registrar(s)`: os dois querem a mesma coisa, o
    socket recem-nascido.
    """

    class Conexao(base):
        def __init__(self, *args, **kw):
            # Bloco de 64 KB em vez dos 8 KB padrao do http.client. Nao muda a
            # velocidade (medido: 757 contra 775 Mbps), muda a CPU: 0,59 s por
            # GB contra 3,01 s, cinco vezes menos. Num app de MONITORAMENTO isso
            # importa: 37,6% de um nucleo durante o teste contamina os proprios
            # numeros que ele mostra na tela.
            kw.setdefault("blocksize", BLOCO)
            super().__init__(*args, **kw)

        def connect(self):
            criar = self._create_connection

            def rastreando(*args, **kw):
                s = criar(*args, **kw)
                registrar(s)            # TCP de pe': ja' da' para derrubar
                concedido = pedir_buffer_de_envio(s, sndbuf)
                if anotar_buffer is not None:
                    anotar_buffer(concedido)
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
        self._sndbuf = 0
        self._lock = threading.Lock()

    def buffer_de_envio(self) -> int:
        """Menor buffer de envio concedido nesta fase, em bytes.

        Menor, e nao o ultimo: o teto da subida e' ditado pelo fluxo mais
        apertado, e um unico socket que ficou com 64 KB puxa a fase inteira.
        Zero significa "ninguem pediu": e' o caso do download e o dos testes.
        """
        with self._lock:
            return self._sndbuf

    def _anotar_buffer(self, concedido: int) -> None:
        if concedido <= 0:
            return
        with self._lock:
            self._sndbuf = concedido if not self._sndbuf else min(self._sndbuf, concedido)

    def esquecer_buffer(self) -> None:
        """Zera a leitura antes de uma fase nova, para nao herdar a anterior."""
        with self._lock:
            self._sndbuf = 0

    def abortar(self) -> None:
        """Derruba na marra tudo que estiver aberto, sem segurar quem chamou.

        Sem isso o cancelamento so' valeria quando o read() em curso voltasse; e
        num socket travado isso e' o timeout inteiro. Fechar o app no meio de um
        teste deixaria a conexao de pe' esperando dado que ninguem quer mais.

        Volta em microssegundos por construcao: aqui ninguem espera trava de
        buffer nem leitura em andamento; so' se mexe no descritor (`_arrebentar`).
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

    def _abrir(self, req: urllib.request.Request, timeout: float, cancelado=None,
               sndbuf: int = 0):
        abridor = urllib.request.build_opener(
            _HandlerHTTP(self._registrar_socket, cancelado, sndbuf, self._anotar_buffer),
            _HandlerHTTPS(self._registrar_socket, cancelado, sndbuf, self._anotar_buffer))
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
          o primeiro da lista apagava a latencia da tela enquanto o download
          (que tenta todos) ia bem;
        - o resolvedor do Windows devolve os enderecos em ordem rotativa, entao
          "o primeiro da lista" era um host DIFERENTE a cada sonda. As medidas
          alternavam 16 e 38 ms e o jitter saia em 21 ms numa conexao que oscila
          2: jitter de diversidade de caminho, nao de oscilacao da rede.

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

    def enviar(self, url: str, cancelado, contar, timeout: float, tamanho: int,
               sndbuf: int = SNDBUF_UPLOAD) -> None:
        corpo = _CorpoContado(tamanho, contar, cancelado, os.urandom(BLOCO))
        cabecalhos = dict(_CABECALHOS)
        cabecalhos["Content-Type"] = "application/octet-stream"
        cabecalhos["Content-Length"] = str(tamanho)
        req = urllib.request.Request(url, data=corpo, method="POST", headers=cabecalhos)
        resp = self._abrir(req, timeout, cancelado, sndbuf)
        try:
            resp.read(BLOCO)
        finally:
            self._fechar(resp)
            self._soltar_sockets()

    def texto(self, url: str, timeout: float, etag: str | None = None):
        """Baixa um documento pequeno (a lista de servidores). (codigo, corpo, etag).

        Leitura com TETO: `LISTA_MAX_BYTES` e' o que separa "buscar uma lista de
        6 KB" de "um endereco sequestrado empurrando um arquivo sem fim para
        dentro de um app de monitoramento". O 304 volta como codigo, e nao como
        excecao, porque para quem chama ele e' a resposta feliz, nada mudou.
        """
        cabecalhos = dict(_CABECALHOS)
        if etag:
            cabecalhos["If-None-Match"] = etag
        req = urllib.request.Request(url, headers=cabecalhos)
        try:
            resp = self._abrir(req, timeout)
        except urllib.error.HTTPError as e:
            if e.code == 304:
                return 304, "", etag
            raise
        try:
            corpo = resp.read(LISTA_MAX_BYTES)
            return (getattr(resp, "status", None) or 200,
                    corpo.decode("utf-8", "replace"), resp.headers.get("ETag"))
        finally:
            self._fechar(resp)
            self._soltar_sockets()


class TesteDeVelocidade:
    """Maquina de estados do teste: latencia, download, upload.

    Roda numa thread so' (mais as dos fluxos), publica o andamento num snapshot
    protegido por trava e para na hora quando mandam parar. Nenhuma thread e'
    non-daemon e nenhum socket sobrevive ao cancelamento: fechar o app no meio
    de um teste nao pode segurar o processo vivo.
    """

    def __init__(self, rede: Rede | None = None, fluxos: int = FLUXOS,
                 duracao: float = DURACAO_S, aquecimento: float = AQUECIMENTO_S,
                 janela_minima: float = JANELA_MINIMA_S, sondas: int = SONDAS,
                 urls_download=PROVEDORES_DOWNLOAD, urls_upload=PROVEDORES_UPLOAD,
                 timeout: float = TIMEOUT_S,
                 tentativas: int = TENTATIVAS_POR_FLUXO,
                 lista_publica: bool = True) -> None:
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
        self._lista_publica = bool(lista_publica)
        """Se a lista publica entra na roda. Desligado, o app anda so' com a
        semente embutida: e' o modo dos testes, que nunca tocam a internet."""

        self._lock = threading.Lock()
        self._parar = threading.Event()
        self._thread: threading.Thread | None = None
        self._orfas: list[threading.Thread] = []
        """Fluxos que nao morreram no prazo da fase deles. Ver `_enterrar_orfas`."""
        self._fixado = servidor_fixado() if self._lista_publica else None
        self._latencias: dict[str, float | None] = {}
        """Ultima varredura. A tela mostra a latencia de quem esta' medindo AGORA,
        e nao a do escolhido: descer na fila sem trocar o numero ao lado seria
        casar o host de um servidor com a latencia de outro."""
        self._estado = self._zerado()

    def _zerado(self) -> dict:
        return {"fase": FASE_OCIOSO, "rodando": False, "progresso": 0.0,
                "parcial": None, "download": None, "upload": None,
                "ping": None, "jitter": None, "erro": None, "aviso": None,
                "servidor": self._download[0].host if self._download else None,
                "servidor_nome": self._download[0].rotulo if self._download else None,
                "servidor_ms": None, "servidor_envio": None,
                "fixado": self._fixado, "candidatos": 0, "responderam": 0,
                "teto_processo": None, "teto_janela": None, "buffer_envio": 0,
                "quando": None}

    def candidatos(self) -> tuple[Provedor, ...]:
        """Todas as casas que este teste conhece: semente mais lista em disco.

        E' o que a tela mostra na lista de "fixar servidor": nao adianta oferecer
        um servidor que o motor nao usaria.
        """
        base = tuple(self._download) + tuple(self._upload)
        extras = lista_em_cache() if self._lista_publica else ()
        return _sem_repetir(base + extras)[:CANDIDATOS_MAXIMOS]

    @property
    def fixado(self) -> str | None:
        return self._fixado

    def fixar(self, host: str | None) -> None:
        """Fixa um servidor (ou volta ao automatico) e grava a escolha.

        Vontade declarada ganha de medicao; mas a fila automatica continua atras
        como reserva: fixar um servidor nao pode ser o mesmo que ficar sem teste
        no dia em que aquela casa estiver fora do ar.
        """
        self._fixado = host or None
        if self._lista_publica:
            fixar_servidor(self._fixado)
        self._publicar(fixado=self._fixado)

    def _publicar(self, **campos) -> None:
        with self._lock:
            if "progresso" in campos:
                # A barra so' anda para frente. Cada tentativa de servidor
                # reinicia o relogio da fase, e sem esta trava a barra caia de
                # 0,60 para 0,08 ao trocar de provedor, na cara do usuario, no
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
        """Encerra de vez, usado ao fechar o app."""
        self.cancel()
        self.aguardar(timeout)

    def aguardar(self, timeout: float = 30.0) -> bool:
        """Espera o teste acabar DE VERDADE: o motor e os fluxos.

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

    def _executar(self) -> None:
        try:
            self._buscar_lista()
            escolha = self._escolher_servidor()
            baixado = self._rodar_fila(FASE_DOWNLOAD, escolha.download)
            enviado = self._rodar_fila(FASE_UPLOAD, escolha.upload)
            self._concluir(baixado, enviado)
        except Exception as e:  # noqa: BLE001: thread solta nao pode morrer calada
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
            avisos.append(f"Download ficou de fora: {dl.erro or 'nenhum servidor respondeu'}.")
        else:
            avisos.extend(_ressalvas("Download", dl))
        if not _medivel(ul.taxa):
            avisos.append(f"Upload ficou de fora: {ul.erro or 'nenhum servidor respondeu'}.")
        else:
            avisos.extend(_ressalvas("Upload", ul))

        if not _medivel(dl.taxa) and not _medivel(ul.taxa):
            # Sem nenhuma das duas taxas nao houve teste de velocidade (o ping
            # sozinho nao mede banda), e ai' e' erro mesmo. A frase precisa
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

    def _buscar_lista(self) -> None:
        """Pede a lista publica em SEGUNDO PLANO, sem segurar o teste.

        A ordem importa e e' contraintuitiva: o teste de hoje anda com o que ja'
        esta' no disco, e o que chegar agora so' enriquece o de amanha. Esperar
        seria pagar o pior dos dois mundos: atraso na fase de latencia para
        acrescentar candidatos que, medidos, ficam a 134 ms.

        A thread nao se chama "speed…" de proposito: ela nao e' fluxo de medicao,
        nao pode ser confundida com um, e nao segura o encerramento do teste.
        """
        if not self._lista_publica or not lista_vencida():
            return
        threading.Thread(target=self._lista_em_segundo_plano, daemon=True,
                         name="dbx-lista-servidores").start()

    def _lista_em_segundo_plano(self) -> None:
        try:
            quantos = atualizar_lista(self._rede)
        except Exception as e:  # noqa: BLE001: thread solta nao morre calada
            _log.debug("atualização da lista falhou: %s", e)
            return
        if quantos:
            _log.info("lista pública de servidores atualizada: %d casas", quantos)

    def _escolher_servidor(self) -> Escolha:
        """Sonda todas as casas, escolhe a melhor e mede o ping DELA.

        Duas medicoes diferentes moram nesta fase, e juntar as duas era o erro
        antigo. A VARREDURA compara casas: poucas sondas em cada uma, em paralelo,
        so' para saber quem esta' perto. O PING descreve a conexao do usuario, e
        para isso precisa de uma sequencia de sondas no MESMO destino: jitter
        calculado com amostras de servidores diferentes mede diversidade de
        caminho, nao oscilacao da rede, e pinta de instavel uma conexao que oscila
        1 ms.

        Se ninguem responder, o teste continua: a fila fica na ordem da semente e
        o download decide. Ping em branco com download de pe' e' informacao; teste
        abortado porque um connect falhou nao e'.
        """
        self._publicar(fase=FASE_LATENCIA)
        candidatos = self.candidatos()
        latencias = self._latencias = self._varrer(candidatos)
        if self._parar.is_set():
            return Escolha(None, self._download, self._upload)
        conhecidos = {p.host for p in self._download} | {p.host for p in self._upload}
        extras = tuple(p for p in candidatos if p.host not in conhecidos)
        escolha = escolher(self._download + tuple(p for p in extras if p.url),
                           self._upload + tuple(_como_upload(p) for p in extras if p.envio),
                           latencias, self._fixado)
        alvo = escolha.servidor
        envio = escolha.upload[0].host if escolha.upload else None
        self._publicar(servidor=alvo.host if alvo else None,
                       servidor_nome=alvo.rotulo if alvo else None,
                       servidor_ms=escolha.latencia_ms, servidor_envio=envio,
                       candidatos=escolha.sondados, responderam=escolha.responderam,
                       progresso=progresso(FASE_LATENCIA, 0.6))
        self._medir_ping(alvo, latencias)
        return escolha

    def _varrer(self, candidatos: tuple[Provedor, ...]) -> dict[str, float | None]:
        """Latencia minima de cada casa, medida em paralelo. {host: ms ou None}.

        Minimo, nunca media: tudo que passa do piso e' fila no caminho, e uma
        sonda azarada nao pode custar a escolha do servidor.

        As threads sao poucas, curtas e daemon, e o prazo e' de relogio: quem nao
        voltou a tempo simplesmente nao opina: o teste ja' tem fila para decidir.
        """
        alvos = [p for p in candidatos if p.host]
        if not alvos:
            return {}
        latencias: dict[str, float | None] = {}
        trava = threading.Lock()
        fila = list(alvos)
        sondas = max(1, min(self._sondas, SONDAS_DA_ESCOLHA))
        prazo = min(self._timeout, 3.0)

        def trabalhar() -> None:
            while not self._parar.is_set():
                with trava:
                    if not fila:
                        return
                    prov = fila.pop(0)
                melhor: float | None = None
                for _ in range(sondas):
                    if self._parar.is_set():
                        return
                    try:
                        ms = self._rede.sondar(prov.host, prov.porta, prazo)
                    except OSError:
                        break   # casa muda: insistir so' gasta o relogio da fase
                    melhor = ms if melhor is None else min(melhor, ms)
                with trava:
                    latencias[prov.host] = melhor
                    feitos = len(latencias)
                self._publicar(progresso=progresso(FASE_LATENCIA,
                                                   0.6 * feitos / len(alvos)))

        threads = [threading.Thread(target=trabalhar, daemon=True, name=f"speed-sonda-{i}")
                   for i in range(min(TRABALHADORES_SONDA, len(alvos)))]
        for t in threads:
            t.start()
        limite = time.monotonic() + PRAZO_DA_ESCOLHA_S
        for t in threads:
            t.join(max(0.0, limite - time.monotonic()))
        vivas = [t for t in threads if t.is_alive()]
        if vivas:
            # Sonda presa e' socket aberto: derrubar aqui evita que ela atravesse
            # a fronteira e consuma link durante a medicao de download.
            self._rede.abortar()
            for t in vivas:
                t.join(0.1)
            with self._lock:
                self._orfas = [t for t in self._orfas + vivas if t.is_alive()]
        return latencias

    def _medir_ping(self, alvo: Provedor | None, latencias: dict) -> None:
        """Sequencia de sondas no servidor escolhido, o ping e o jitter da tela."""
        if alvo is None:
            return
        medidas: list[float] = []
        conhecida = latencias.get(alvo.host)
        if conhecida is not None:
            medidas.append(conhecida)
        for i in range(self._sondas):
            if self._parar.is_set():
                return
            try:
                medidas.append(self._rede.sondar(alvo.host, alvo.porta,
                                                 min(self._timeout, 3.0)))
            except OSError:
                pass            # sonda perdida vira jitter, nao erro: o download decide
            ms, jitter = latencia(medidas)
            self._publicar(ping=ms, jitter=jitter,
                           progresso=progresso(FASE_LATENCIA,
                                               0.6 + 0.4 * (i + 1) / self._sondas))
            self._parar.wait(0.05)

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
            # O nome na tela e' o de quem esta' medindo AGORA, e nao o do primeiro
            # da fila que ja' recusou. As duas fases tem campo proprio: com um
            # campo so', a tela dizia "via fulano" ao lado de um numero de upload
            # que tinha vindo de outra casa: engana justamente quem for conferir.
            campos = {"parcial": None}
            if fase == FASE_DOWNLOAD:
                campos.update(servidor=prov.host, servidor_nome=prov.rotulo,
                              servidor_ms=self._latencias.get(prov.host))
            else:
                campos["servidor_envio"] = prov.host
            self._publicar(**campos)

            rodada = self._transferir(fase, prov)
            if _medivel(rodada.taxa):
                # Publicado junto com `parcial=None` num unico update: separar as
                # duas coisas deixava um quadro em que a tela ainda mostrava a
                # parcial cinzenta em cima do valor ja' fechado.
                self._publicar(parcial=None, **{fase: rodada.taxa})   # "download"/"upload"
                return _Medida(rodada.taxa, None, prov, indice > 0, rodada.degradado,
                               rodada.contaminado, rodada.teto_processo,
                               rodada.teto_janela, rodada.inflado)
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
        self._rede.esquecer_buffer()
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
        janela = janela_util(amostras, self._aquecimento, self._janela_minima)
        taxa = mbps(janela[1], janela[0]) if janela else None
        if _medivel(taxa) and trilho.mortos * 2 >= self._fluxos:
            # Metade dos fluxos morreu: o que sobrou mediu um pedaco da banda e
            # devolveria algo como 150 Mbps num link de 600, numero baixo com
            # cara de medicao, que e' pior que erro nenhum. Vale mais tentar o
            # proximo servidor da fila.
            _log.info("fase %s em %s: %d de %d fluxos cairam, medida descartada",
                      fase, prov.host, trilho.mortos, self._fluxos)
            taxa = None
        tetos = self._tetos(fase, prov, trilho, janela)
        if not _medivel(taxa):
            return _Rodada(None, trilho.falhas(), False, entregou, contaminado, *tetos)
        return _Rodada(taxa, (), trilho.mortos > 0, True, contaminado, *tetos)

    def _tetos(self, fase: str, prov: Provedor, trilho: _Trilho,
               janela: tuple[float, int] | None) -> tuple[float | None, float | None, bool]:
        """As duas contas que dizem se o numero e' do link ou do app.

        So' valem na subida. O download nao tem teto de janela (o Windows
        auto-ajusta a de recepcao) e o custo de CPU dele e' uma fracao do da
        subida, entao trazer as duas contas para ca' seria enfeite com ar de
        diagnostico.

        A terceira resposta e' a mais importante e a menos obvia: `inflado`. O
        contador soma o que foi entregue ao SOCKET, e com um buffer de 4 MB por
        fluxo isso pode ser 16 MB que o servidor ainda nao viu. Em regime esse
        excesso e' um offset constante e cancela na subtracao; mas se a janela de
        medicao for curta, ele vira a medida inteira. Medido: numa janela de 0,5 s
        o numero mentiria +323%. Entao, quando o buffer somado chega perto do
        volume da janela, o resultado sai com ressalva em vez de sair limpo.
        """
        if fase != FASE_UPLOAD:
            return None, None, False
        buffer_ = self._rede.buffer_de_envio()
        processo = teto_do_processo(trilho.contador.total, trilho.cpu)
        # A ida e volta que interessa e' a de QUEM esta' recebendo o envio: com as
        # duas fases em casas diferentes, usar o ping do servidor de download
        # calcularia o teto de subida com a distancia errada.
        rtt = self._latencias.get(prov.host) or self.snapshot().get("ping")
        janela_teto = teto_da_janela(buffer_, rtt, self._fluxos)
        inflado = bool(janela and buffer_
                       and buffer_ * self._fluxos > FOLGA_DE_BUFFER * janela[1])
        self._publicar(teto_processo=processo, teto_janela=janela_teto,
                       buffer_envio=buffer_)
        return processo, janela_teto, inflado

    def _encerrar_fluxos(self, threads: list[threading.Thread]) -> None:
        """Fecha os sockets da fase e espera os fluxos dentro de um orcamento.

        Derrubar as conexoes aqui e' o que faz o encerramento ser imediato: o
        sinal de fim so' e' lido ENTRE dois read(), entao um socket pendurado
        seguraria a fase pelo timeout inteiro.

        O `join` gasta o orcamento SOMADO, e nao 50 ms garantidos por fluxo depois
        do prazo: era assim que a fase seguia em frente com os fluxos vivos. Quem
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
        orcamento) e, se mesmo assim sobrar alguem, devolve True: o resultado sai
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

        Reabrir e' necessario porque o arquivo do servidor tem tamanho fixo: num
        link rapido ele acaba antes do relogio, e sem a repeticao a segunda metade
        da janela seria medida como zero.

        E reabre tambem depois de ERRO, com recuo, e nao so' depois do fim do
        arquivo: um fluxo que morre no meio e nao volta deixa a fase inteira
        medindo com menos banda do que o link tem. So' desiste de vez quando o
        servidor recusa por decisao propria (4xx, incluindo o 429) ou quando as
        tentativas acabam; e a desistencia fica registrada, porque medida com
        fluxo faltando nao pode passar por medida boa.

        Reabrir tem PISO. O caminho de sucesso nao tinha nenhum: resposta que
        termina sem erro e sem bytes (Content-Length: 0, 204, objeto cortado) fazia
        o laco girar solto: milhoes de aberturas por fase, uma tempestade de
        conexoes contra o provedor e um "Mbps" que media a reconexao do app. Agora
        abertura que nao entrega volume conta como tropeco, com recuo e com
        desistencia registrada, igual a um erro.
        """
        # O tempo de CPU desta thread e' medido de ponta a ponta: e' com ele que
        # `teto_do_processo` responde se o numero de upload fala da internet ou do
        # proprio app. `thread_time` conta so' esta thread; `process_time`
        # contaria tambem o coletor e a interface, e o teto sairia pessimista por
        # culpa de trabalho que nao e' do teste.
        cpu_inicial = time.thread_time()
        try:
            self._correr_fluxo(fase, prov, trilho)
        finally:
            trilho.gastar_cpu(time.thread_time() - cpu_inicial)

    def _correr_fluxo(self, fase: str, prov: Provedor, trilho: _Trilho) -> None:
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


def _texto_taxa(mbps_: float) -> str:
    """Mbps ou Gbps, conforme o tamanho: "1400 Mbps" ninguem le' de primeira."""
    return f"{mbps_ / 1000:.1f} Gbps".replace(".", ",") if mbps_ >= 1000 else f"{mbps_:.0f} Mbps"


def _ressalvas(rotulo: str, medida: _Medida) -> list[str]:
    """O que precisa ser dito sobre um numero que fechou mesmo assim.

    Cair para o segundo servidor da fila deixou de ser motivo de alarme: os
    primeiros da lista estao todos em Sao Paulo e medem igual. Ja' o servidor fora
    do pais avisa SEMPRE, e nao so' quando e' reserva: com a escolha automatica e
    a lista publica (que nao tem uma casa sequer no Brasil), a casa distante pode
    perfeitamente ser a primeira da fila, e ai' o numero baixo sairia sem uma
    palavra de explicacao.

    As duas ultimas ressalvas sao a promessa central do upload: quando o numero
    encosta no teto da janela de envio ou no teto de CPU do processo, ele deixou
    de falar sobre a internet. Dizer "812 Mbps" e calar sobre o teto de 830 e'
    apresentar o limite do app como se fosse o limite do link.
    """
    fora: list[str] = []
    prov = medida.provedor
    if prov is not None and not prov.perto:
        fora.append(f"{rotulo} medido em {prov.host}, fora do país: "
                    f"o valor sai abaixo do real.")
    elif medida.reserva and prov is not None:
        fora.append(f"{rotulo} medido pelo servidor reserva ({prov.host}).")
    if medida.taxa is not None:
        if medida.teto_janela and medida.taxa >= TETO_DUVIDA * medida.teto_janela:
            fora.append(f"{rotulo} bateu no teto da janela de envio do Windows "
                        f"(~{_texto_taxa(medida.teto_janela)}): o número é o limite "
                        f"do envio, não o da sua internet.")
        if medida.teto_processo and medida.taxa >= TETO_DUVIDA * medida.teto_processo:
            fora.append(f"{rotulo} bateu no teto deste app "
                        f"(~{_texto_taxa(medida.teto_processo)} é o que o Python "
                        f"empurra com um núcleo): o link pode ser mais rápido que isso.")
    if medida.inflado:
        fora.append(f"Janela de {rotulo.lower()} curta demais para o buffer de envio; "
                    f"o valor pode sair acima do real.")
    if medida.degradado:
        fora.append(f"Parte dos fluxos de {rotulo.lower()} caiu no meio; "
                    f"o valor pode sair abaixo do real.")
    if medida.contaminado:
        # Medir upload com download ainda no ar da' um numero baixo com cara de
        # numero bom. Se nao deu para enterrar a fase anterior a tempo, isso e'
        # dito; calar seria repetir o defeito que a ressalva existe para cobrir.
        fora.append(f"Fluxos da fase anterior ainda estavam no ar durante o "
                    f"{rotulo.lower()}; o valor pode sair abaixo do real.")
    return fora


def _fila(itens) -> tuple[Provedor, ...]:
    """Aceita URLs soltas ou Provedores: string vira Provedor com os padroes."""
    if isinstance(itens, (str, Provedor)):
        itens = (itens,)
    return tuple(i if isinstance(i, Provedor) else Provedor(str(i)) for i in itens)


def _host(url: str) -> str:
    return urllib.parse.urlsplit(url).hostname or url


def _porta(url: str) -> int:
    """Porta do connect da latencia: nem todo servidor de teste fala TLS.

    Fixar 443 sondava uma porta que o servidor podia nem estar ouvindo: a
    latencia sumia da tela por um detalhe que nao tem nada a ver com a rede.
    """
    partes = urllib.parse.urlsplit(url)
    if partes.port:
        return partes.port
    return 80 if partes.scheme == "http" else PORTA_TLS
