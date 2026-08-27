"""Conta e maquina de estados do teste de velocidade.

Nenhum teste aqui toca a internet: o transporte e' um duble. O que esta' sendo
protegido e' a honestidade do numero: nao subestimar link rapido por causa do
slow start, nao somar errado os fluxos paralelos e, acima de tudo, nunca mostrar
zero Mbps quando na verdade a rede caiu.

A segunda metade do arquivo cuida da outra promessa: contar direito o que deu
errado. Falha de um servidor nao pode virar frase generica sobre "conexao caida",
resultado que ja' fechou nao pode ser apagado por uma fase que falhou depois, e
medicao feita com metade dos fluxos mortos nao pode sair como se fosse boa.
"""
import json
import socket
import threading
import time
import urllib.error

import pytest

from dbxstats.core import units
from dbxstats.sensors import speedtest as sp


def _marcas(pares):
    """Marcas (instante, bytes acumulados) a partir de pares legiveis."""
    return [(float(t), int(b)) for t, b in pares]


# ── conversao ────────────────────────────────────────────────────────────────
def test_mbps_usa_megabit_decimal():
    """A operadora vende em megabit decimal; usar 2^20 daria 4,8% a menos."""
    assert sp.mbps(12_500_000, 1.0) == 100.0


def test_mbps_sem_tempo_nao_inventa_numero():
    assert sp.mbps(1000, 0.0) is None


# ── taxa ─────────────────────────────────────────────────────────────────────
def test_aquecimento_do_tcp_fica_fora_da_conta():
    """Slow start e' o que fazia um link de 800 Mbps ser lido como 200.

    O primeiro segundo anda devagar (1 MB) e o resto anda no ritmo real
    (12,5 MB/s = 100 Mbps). Contar tudo junto daria ~54 Mbps.
    """
    amostras = _marcas([(0.0, 0), (1.0, 1_000_000),
                        (2.0, 13_500_000), (3.0, 26_000_000)])
    assert sp.taxa_estavel(amostras, aquecimento=1.0, janela_minima=0.5) == 100.0


def test_serie_curta_demais_ainda_devolve_o_conservador():
    """Teste interrompido cedo: melhor um numero baixo que um travessao."""
    amostras = _marcas([(0.0, 0), (0.5, 6_250_000)])
    assert sp.taxa_estavel(amostras, aquecimento=5.0, janela_minima=0.1) == 100.0


def test_uma_marca_so_nao_e_medida():
    assert sp.taxa_estavel(_marcas([(0.0, 999)])) is None


def test_janela_curta_demais_nao_vira_numero():
    """Dividir bytes por um intervalo minusculo amplifica ruido de agendamento."""
    amostras = _marcas([(0.0, 0), (0.05, 5_000_000)])
    assert sp.taxa_estavel(amostras, aquecimento=0.0, janela_minima=0.5) is None


def test_nada_transferido_nao_vira_zero_mbps():
    """Zero Mbps com cara de medicao e' mentira; quem nao mediu devolve None."""
    amostras = _marcas([(0.0, 0), (6.0, 0)])
    assert sp.taxa_estavel(amostras, aquecimento=1.0) is None


def test_um_byte_solto_tambem_nao_e_medicao():
    """A guarda em bytes so' pegava o zero exato; um byte escapava por baixo.

    `round(x, 2)` transforma qualquer coisa abaixo de ~625 B/s em exatamente 0.0,
    e esse 0.0 percorria o modulo inteiro como medida boa: fase pronta, erro
    nenhum, aviso nenhum, badge verde. Toda a faixa de 0 a 6 KB/s (tarpit de
    anti-abuso, portal cativo, link agonizante) virava "0.0 Mbps" com selo de
    medicao limpa.
    """
    assert sp.taxa_estavel(_marcas([(0.0, 0), (6.0, 1)]),
                           aquecimento=1.5, janela_minima=0.5) is None
    assert sp.mbps(0, 1.0) is None
    assert sp.mbps(1, 1.0) is None
    assert sp.mbps(600, 1.0) is None                   # 0,0048 Mbps -> "0.0" na tela


def test_parcial_sem_byte_novo_nao_escreve_zero_no_tile():
    """Servidor de TTFB alto: a parcial dizia "0.0 Mbps · medindo…" sem nada ter
    chegado. Enquanto nao chega byte, o certo e' travessao, nao um numero."""
    assert sp.taxa_instantanea(_marcas([(0.0, 0), (0.1, 0), (0.2, 0)])) is None
    assert sp.taxa_instantanea(_marcas([(0.0, 5), (0.1, 5), (0.2, 6)])) is None


def test_taxa_instantanea_olha_so_o_fim():
    """O numero que corre na tela tem que reagir, nao carregar a media da fase."""
    amostras = _marcas([(0.0, 0), (5.0, 1_000_000),
                        (5.5, 7_250_000), (6.0, 13_500_000)])
    assert sp.taxa_instantanea(amostras, janela=1.0) == 100.0


# ── contador dos fluxos ──────────────────────────────────────────────────────
def test_contador_soma_todos_os_fluxos():
    """Fluxo paralelo e' a razao de existir do teste: perder soma = subestimar."""
    contador = sp.Contador()
    threads = [threading.Thread(target=lambda: [contador.somar(1000) for _ in range(200)])
               for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert contador.total == 8 * 200 * 1000


# ── latencia ─────────────────────────────────────────────────────────────────
def test_latencia_e_o_piso_das_sondas():
    """Sobra em cima do minimo e' fila no caminho, nunca velocidade sobrando."""
    ms, jitter = sp.latencia([18.0, 16.2, 20.2, 16.2])
    assert ms == 16.2
    assert jitter == 4.0       # mediana das diferencas entre sondas seguidas


def test_uma_sonda_azarada_nao_pinta_a_conexao_de_instavel():
    """Sequencia real: cinco connects colados e um que caiu numa fila.

    Com media, esse unico 40 ms virava "jitter de 10 ms" numa conexao que oscila
    menos de 1 ms, e o usuario iria caçar problema onde nao havia.
    """
    ms, jitter = sp.latencia([16.4, 16.8, 16.7, 16.0, 40.4, 16.3])
    assert ms == 16.0
    assert jitter < 1.5


def test_latencia_sem_sonda_nenhuma():
    assert sp.latencia([]) == (None, None)


def test_uma_sonda_da_latencia_mas_nao_jitter():
    assert sp.latencia([21.0]) == (21.0, None)


# ── barra de progresso ───────────────────────────────────────────────────────
def test_progresso_nunca_anda_para_tras():
    marcos = [sp.progresso(fase, f)
              for fase in sp.FASES for f in (0.0, 0.5, 1.0)]
    assert marcos == sorted(marcos)
    assert sp.progresso(sp.FASE_PRONTO, 0.0) == 1.0


def test_progresso_de_fase_desconhecida_fica_no_zero():
    assert sp.progresso(sp.FASE_OCIOSO, 0.5) == 0.0


# ── mensagens ────────────────────────────────────────────────────────────────
def test_falha_de_dns_vira_frase_sobre_conexao():
    import socket
    texto = sp.mensagem_de_erro(socket.gaierror(11001, "getaddrinfo failed"))
    assert "sem conexão" in texto
    assert "gaierror" not in texto


def test_timeout_vira_frase_sobre_o_servidor():
    assert "não respondeu" in sp.mensagem_de_erro(TimeoutError())


def test_http_recusado_diz_o_codigo():
    erro = urllib.error.HTTPError("http://x", 403, "Forbidden", {}, None)
    assert "403" in sp.mensagem_de_erro(erro)


def test_limite_de_requisicoes_manda_esperar_e_nao_culpa_a_internet():
    """429 e' o unico codigo cuja acao certa e' nao fazer nada por alguns minutos.

    Empacotado no texto generico de "recusou o pedido" (ou pior, no de "conexao
    caiu", que era o que sobrava na tela), ele mandava a pessoa mexer no roteador
    por causa de um castigo por volume que expira sozinho.
    """
    texto = sp.mensagem_de_erro(urllib.error.HTTPError("u", 429, "Too Many Requests", {}, None))
    assert "esperar" in texto and "minutos" in texto
    assert "caiu" not in texto


def test_servidor_com_defeito_nao_vira_recusa():
    """5xx e' problema do outro lado, e nao pedido malfeito daqui."""
    texto = sp.mensagem_de_erro(urllib.error.HTTPError("u", 503, "Unavailable", {}, None))
    assert "503" in texto and "fora do ar" in texto


def test_falha_de_tls_nao_vaza_texto_de_maquina():
    """Proxy corporativo que intercepta TLS saia como frase, nao como traceback.

    Antes esse caso caia no ramo final e imprimia em vermelho, no card, algo como
    "[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed", exatamente o
    que o modulo promete nunca mostrar.
    """
    import ssl
    texto = sp.mensagem_de_erro(urllib.error.URLError(ssl.SSLError("CERTIFICATE_VERIFY_FAILED")))
    assert "CERTIFICATE" not in texto
    assert "segura" in texto


def test_erro_desconhecido_nao_vira_traceback_na_tela():
    assert sp.mensagem_de_erro(ValueError("boom")) == "não consegui falar com o servidor de teste"


# ── fila de servidores: escolha da mensagem ──────────────────────────────────
def test_erro_da_cadeia_guarda_o_429_e_nao_o_ultimo_tropeco():
    """O caso real: Cloudflare em 429 e reserva caindo por RemoteDisconnected.

    Guardando so' a ultima falha, o que chegava na tela era "a conexao caiu no
    meio do teste", e a unica informacao acionavel do teste inteiro (esperar
    alguns minutos) era descartada no caminho.
    """
    falhas = [("speed.cloudflare.com",
               urllib.error.HTTPError("u", 429, "Too Many Requests", {}, None)),
              ("ash-speed.hetzner.com", ConnectionResetError("conexão perdida"))]
    texto = sp.erro_da_cadeia(falhas, 2)
    assert "esperar" in texto
    assert "speed.cloudflare.com" in texto


def test_erro_da_cadeia_diz_que_foi_a_fila_inteira():
    """Dizer quantas casas falharam importa; culpar a casa errada importa mais.

    Tres provedores em redes independentes, calados ao mesmo tempo, sao a prova
    mais forte que existe de que o problema esta' do lado de ca'. A frase antiga
    reunia essa evidencia e escrevia "nenhum dos 3 servidores de teste respondeu;
    a: o servidor de teste nao respondeu a tempo": no singular, apontando o dedo
    justamente para quem nao tem culpa, e sem dizer o que fazer.
    """
    falhas = [("a", TimeoutError()), ("b", TimeoutError()), ("c", TimeoutError())]
    texto = sp.erro_da_cadeia(falhas, 3)
    assert "3 servidores" in texto            # continua dizendo que foi a fila toda
    assert "sua conexão" in texto             # e para onde olhar
    assert "confira" in texto                 # ... e o que fazer
    assert "o servidor de teste não respondeu" not in texto


def test_fila_que_respondeu_com_codigo_nao_diz_que_ninguem_respondeu():
    """404 na fila inteira e' resposta, e resposta e' informacao, nao silencio."""
    def _404(host):
        return (host, urllib.error.HTTPError("u", 404, "Not Found", {}, None))

    texto = sp.erro_da_cadeia([_404("a"), _404("b")], 2)
    assert "responderam" in texto and "nenhum aceitou medir" in texto
    assert "404" in texto
    assert "não respondeu" not in texto


def test_fila_que_entregou_bytes_e_caiu_aponta_para_a_conexao_de_quem_mede():
    """Todos mandaram dados e as transferencias cairam: a culpa nao e' das casas."""
    falhas = [("a", ConnectionResetError("caiu"), True),
              ("b", ConnectionResetError("caiu"), True)]
    texto = sp.erro_da_cadeia(falhas, 2)
    assert "enviaram dados" in texto and "sua conexão" in texto
    assert "não responderam" not in texto


def test_fila_que_aceitou_e_nao_mandou_nada_fala_em_portal_de_login():
    """Aceitar a conexao e nao entregar byte tem cheiro de portal cativo."""
    falhas = [("a", sp.RespostaMagra("vazio"), False),
              ("b", sp.RespostaMagra("vazio"), False)]
    texto = sp.erro_da_cadeia(falhas, 2)
    assert "não enviaram dados" in texto and "portal de login" in texto


def test_erro_da_cadeia_com_um_servidor_so_nao_inventa_plural():
    assert sp.erro_da_cadeia([("a", TimeoutError())], 1) == "o servidor de teste não respondeu a tempo"


# ── provedores ───────────────────────────────────────────────────────────────
def test_arquivo_estatico_nao_leva_cache_buster():
    """O bug que deixava o app sem NENHUM servidor de download.

    A Hetzner derruba a conexao sem responder quando a URL tem querystring, e o
    cache-buster era aplicado em toda URL. Com a Cloudflare de castigo, o
    principal recusava e a reserva quebrava sozinha; o teste nao media nada.
    """
    prov = sp.Provedor("https://ash-speed.hetzner.com/100MB.bin")
    assert prov.pedido() == "https://ash-speed.hetzner.com/100MB.bin"


def test_endpoint_com_querystring_continua_driblando_cache():
    """Quem ja' le' parametro aguenta mais um; cache de proxy inflaria o numero."""
    prov = sp.Provedor("https://speed.cloudflare.com/__down?bytes=90000000")
    pedido = prov.pedido()
    assert pedido.startswith("https://speed.cloudflare.com/__down?bytes=90000000&nocache=")
    assert prov.pedido() != pedido      # endereco novo a cada reabertura


def test_fila_padrao_comeca_perto_de_casa_e_tem_plano_c():
    """Servidor longe mede o RTT, nao o link: Ashburn da' 72 Mbps num link de 600.

    Tambem protege o upload, que antes nao tinha plano B nenhum: um tropeco do
    unico endpoint apagava o numero inteiro.
    """
    assert len(sp.PROVEDORES_DOWNLOAD) >= 3
    assert sp.PROVEDORES_DOWNLOAD[0].perto and sp.PROVEDORES_DOWNLOAD[1].perto
    assert len({p.host for p in sp.PROVEDORES_DOWNLOAD}) == len(sp.PROVEDORES_DOWNLOAD)
    assert len(sp.PROVEDORES_UPLOAD) >= 2


class _SocketFalso:
    """Socket de mentira: o custo do connect depende do endereco chamado."""

    conectados: list = []

    def __init__(self, familia, tipo, proto):
        self.quebrado = False

    def settimeout(self, t):
        pass

    def connect(self, endereco):
        _SocketFalso.conectados.append(endereco[0])
        if endereco[0] == "morto":
            raise OSError("recusado")
        time.sleep(0.002 if endereco[0] == "rapido" else 0.02)

    def close(self):
        pass


def _dns_rotativo(monkeypatch, enderecos):
    """Imita o resolvedor do Windows, que devolve os enderecos em ordem rotativa."""
    contagem = {"n": 0}

    def falso(host, porta, **kw):
        contagem["n"] += 1
        giro = contagem["n"] % len(enderecos)
        ordem = enderecos[giro:] + enderecos[:giro]
        return [(2, 1, 6, "", (e, porta)) for e in ordem]

    monkeypatch.setattr(sp.socket, "getaddrinfo", falso)
    monkeypatch.setattr(sp.socket, "socket", _SocketFalso)
    _SocketFalso.conectados = []
    return contagem


def test_sonda_fixa_o_endereco_em_vez_de_alternar_entre_hosts(monkeypatch):
    """Nome com varios IPs sondado "no primeiro da lista" mede hosts diferentes.

    O resolvedor do Windows rotaciona a ordem, entao as sondas iam alternando de
    destino: 16 ms, 38 ms, 16 ms, 38 ms, e o jitter saia em 21 ms numa conexao
    que oscila 2. Isso e' diversidade de caminho com nome de instabilidade, e
    manda o usuario caçar defeito onde nao ha'.
    """
    contagem = _dns_rotativo(monkeypatch, ["rapido", "lento"])
    rede = sp.Rede()
    medidas = [rede.sondar("x", 80, 1.0) for _ in range(4)]
    assert contagem["n"] == 1, "resolveu o nome de novo a cada sonda"
    assert _SocketFalso.conectados[2:] == ["rapido"] * 3
    assert max(medidas) < 15.0                 # ninguem caiu no endereco lento


def test_sonda_esquece_o_endereco_que_parou_de_responder(monkeypatch):
    """Fixar endereco nao pode virar teimosia: se ele morre, resolve de novo."""
    contagem = _dns_rotativo(monkeypatch, ["rapido", "lento"])
    rede = sp.Rede()
    rede.sondar("x", 80, 1.0)
    rede._enderecos[("x", 80)] = (2, 1, 6, ("morto", 80))
    with pytest.raises(OSError):
        rede.sondar("x", 80, 1.0)
    assert rede.sondar("x", 80, 1.0) < 15.0
    assert contagem["n"] == 2


def test_porta_da_sonda_segue_o_esquema_da_url():
    """A Linode de Sao Paulo so' serve em HTTP; sondar 443 fixo era chutar porta."""
    assert sp.Provedor("http://speedtest.gru1.linode.com/x.bin").porta == 80
    assert sp.Provedor("https://cachefly.cachefly.net/x").porta == 443


# ── maquina de estados (com duble de rede) ───────────────────────────────────
class RedeFalsa(sp.Rede):
    """Transporte de mentira: entrega bytes na hora, sem socket nenhum."""

    def __init__(self, por_chamada=1_000_000, falhar_download=None,
                 falhar_upload=None, sonda=15.0) -> None:
        super().__init__()
        self.por_chamada = por_chamada
        self.falhar_download = falhar_download
        self.falhar_upload = falhar_upload
        self.sonda = sonda
        self.urls_baixadas: list[str] = []

    def sondar(self, host, porta, timeout):
        if self.sonda is None:
            raise OSError("sem rota")
        return self.sonda

    def baixar(self, url, cancelado, contar, timeout):
        self.urls_baixadas.append(url)
        if self.falhar_download is not None:
            raise self.falhar_download
        while not cancelado():
            contar(self.por_chamada)
            time.sleep(0.01)

    def enviar(self, url, cancelado, contar, timeout, tamanho):
        if self.falhar_upload is not None:
            raise self.falhar_upload
        while not cancelado():
            contar(self.por_chamada)
            time.sleep(0.01)


class RedeDirigida(sp.Rede):
    """Rede falsa com roteiro por host: quem falha, com o que, e quem entrega.

    `roteiro` mapeia host -> excecao a levantar (ou None para entregar bytes).
    `latencias` mapeia host -> ms (ou None para "essa casa nao responde"), que e'
    como se monta um cenario de escolha automatica sem tocar na internet.
    """

    def __init__(self, roteiro=None, por_chamada=1_000_000, sonda=15.0,
                 demora=0.0, latencias=None) -> None:
        super().__init__()
        self.roteiro = dict(roteiro or {})
        self.por_chamada = por_chamada
        self.sonda = sonda
        self.demora = demora
        self.latencias = dict(latencias or {})
        self.chamadas: list[tuple[str, str]] = []
        self._trava = threading.Lock()
        self.motor = None
        self.espiado: list[dict] = []

    def sondar(self, host, porta, timeout):
        ms = self.latencias.get(host, self.sonda)
        if ms is None:
            raise OSError("sem rota")
        return ms

    def _correr(self, fase, url, cancelado, contar):
        host = sp._host(url)
        with self._trava:
            self.chamadas.append((fase, host))
        if self.demora:
            time.sleep(self.demora)
        falha = self.roteiro.get(host)
        if falha is not None:
            raise falha
        while not cancelado():
            contar(self.por_chamada)
            time.sleep(0.01)

    def baixar(self, url, cancelado, contar, timeout):
        self._correr("download", url, cancelado, contar)

    def enviar(self, url, cancelado, contar, timeout, tamanho):
        if self.motor is not None and not self.espiado:
            # Retrato do snapshot no instante em que a fase de upload comeca:
            # e' onde se ve' se o download ja' chegou na tela.
            self.espiado.append(self.motor.snapshot())
        self._correr("upload", url, cancelado, contar)


def _motor(rede, **kw):
    """Motor com a mesma logica, so' que em escala de teste (frações de segundo).

    `lista_publica=False` nao e' detalhe: com ela ligada o motor leria o servidor
    fixado do disco e mandaria uma thread buscar a lista do LibreSpeed na
    internet. Teste que toca a rede mede o dia, nao o codigo.
    """
    padrao = dict(fluxos=2, duracao=0.4, aquecimento=0.1, janela_minima=0.05,
                  sondas=2, timeout=1.0, lista_publica=False)
    padrao.update(kw)
    motor = sp.TesteDeVelocidade(rede=rede, **padrao)
    if isinstance(rede, RedeDirigida):
        rede.motor = motor
    return motor


def _429():
    return urllib.error.HTTPError("u", 429, "Too Many Requests", {}, None)


def test_teste_completo_publica_as_tres_medidas():
    motor = _motor(RedeFalsa())
    assert motor.start() is True
    assert motor.aguardar(15.0), "o motor nao terminou sozinho"
    s = motor.snapshot()
    assert s["fase"] == sp.FASE_PRONTO
    assert s["rodando"] is False
    assert s["download"] > 0 and s["upload"] > 0
    assert s["ping"] == 15.0
    assert s["erro"] is None and s["aviso"] is None
    assert s["progresso"] == 1.0


def test_nao_comeca_duas_vezes():
    """Dois testes ao mesmo tempo dividiriam a banda e mediriam metade cada um."""
    motor = _motor(RedeFalsa())
    assert motor.start() is True
    assert motor.start() is False
    motor.stop(5.0)


def test_rede_fora_do_ar_vira_erro_e_nao_zero():
    """O caso que mais importa: sem internet a tela diz o que houve."""
    import socket
    motor = _motor(RedeFalsa(falhar_download=socket.gaierror(11001, "getaddrinfo failed"),
                             falhar_upload=socket.gaierror(11001, "getaddrinfo failed"),
                             sonda=None))
    motor.start()
    assert motor.aguardar(20.0)
    s = motor.snapshot()
    assert s["fase"] == sp.FASE_ERRO
    assert s["download"] is None and s["upload"] is None
    assert s["ping"] is None
    assert "sem conexão" in s["erro"]


def test_servidor_principal_fora_cai_no_reserva():
    """Plano B existe para o dia em que a Cloudflare esta' bloqueada na rede."""
    rede = RedeDirigida({"principal": _429()})
    motor = _motor(rede, urls_download=("https://principal/x", "https://reserva/y"))
    motor.start()
    assert motor.aguardar(15.0)
    s = motor.snapshot()
    assert s["fase"] == sp.FASE_PRONTO
    assert s["download"] > 0
    assert s["servidor"] == "reserva"
    assert "reserva" in s["aviso"]


def test_terceiro_servidor_da_fila_ainda_salva_a_medicao():
    """Dois fora e um de pe' e' o cenario do dia do 429: a fila tem que ir ate o fim.

    Com "principal + reserva" so', o mesmo dia terminava sem medida nenhuma.
    """
    rede = RedeDirigida({"um": _429(), "dois": ConnectionResetError("caiu")})
    motor = _motor(rede, urls_download=("https://um/a", "https://dois/b", "https://tres/c"))
    motor.start()
    assert motor.aguardar(20.0)
    s = motor.snapshot()
    assert s["fase"] == sp.FASE_PRONTO
    assert s["download"] > 0
    assert s["servidor"] == "tres"                     # fica registrado quem mediu
    assert [h for _, h in rede.chamadas if h == "tres"]


def test_todos_os_servidores_fora_diz_que_foi_a_fila_inteira():
    """Quando nada responde, a frase precisa dizer isso, e nunca sair 0 Mbps."""
    rede = RedeDirigida({"um": _429(), "dois": _429(), "tres": _429()},
                        sonda=None)
    motor = _motor(rede, urls_download=("https://um/a", "https://dois/b", "https://tres/c"),
                   urls_upload=("https://um/up",))
    motor.start()
    assert motor.aguardar(20.0)
    s = motor.snapshot()
    assert s["fase"] == sp.FASE_ERRO
    assert s["download"] is None and s["upload"] is None
    assert "3 servidores" in s["erro"]                 # foi a fila inteira
    assert "responderam" in s["erro"]                  # e elas RESPONDERAM: 429 e' resposta
    assert "esperar" in s["erro"]                      # o 429 sobrevive ate a tela


def test_servidor_distante_avisa_que_o_numero_sai_baixo():
    """Ashburn mede 72 Mbps num link de 600: sem ressalva, isso vira reclamacao
    contra a operadora."""
    rede = RedeDirigida({"perto": _429()})
    motor = _motor(rede, urls_download=(sp.Provedor("https://perto/a"),
                                        sp.Provedor("https://longe/b", perto=False)))
    motor.start()
    assert motor.aguardar(20.0)
    s = motor.snapshot()
    assert s["fase"] == sp.FASE_PRONTO
    assert "fora do país" in s["aviso"] and "abaixo do real" in s["aviso"]


def test_upload_falho_nao_derruba_o_resto():
    """Endpoint de envio e' o elo fraco; download e ping continuam valendo."""
    motor = _motor(RedeFalsa(falhar_upload=OSError("recusado")))
    motor.start()
    assert motor.aguardar(20.0)
    s = motor.snapshot()
    assert s["fase"] == sp.FASE_PRONTO
    assert s["download"] > 0
    assert s["upload"] is None
    assert "Upload ficou de fora" in s["aviso"]


def test_download_fora_nao_apaga_upload_e_ping():
    """A assimetria antiga: upload que falha virava aviso, download que falha
    virava fracasso total.

    A tela ficava se contradizendo: Upload e Latencia com numeros validos ao lado
    de um "nao deu para medir" em vermelho, e o usuario jogava fora duas medidas
    boas para refazer o teste.
    """
    rede = RedeDirigida({"dl": _429()})
    motor = _motor(rede, urls_download=("https://dl/a",), urls_upload=("https://ul/b",))
    motor.start()
    assert motor.aguardar(20.0)
    s = motor.snapshot()
    assert s["fase"] == sp.FASE_PRONTO
    assert s["download"] is None
    assert s["upload"] > 0
    assert s["ping"] == 15.0
    assert s["quando"] is not None
    assert "Download ficou de fora" in s["aviso"] and "esperar" in s["aviso"]


def test_download_ja_esta_na_tela_quando_o_upload_comeca():
    """Numero que fechou aparece na hora, e nao no fim do teste inteiro.

    Sao 6 a 8 segundos de fase de upload; segurar o download ate la' faz parecer
    que o app travou.
    """
    rede = RedeDirigida()
    motor = _motor(rede, urls_download=("https://dl/a",), urls_upload=("https://ul/b",))
    motor.start()
    assert motor.aguardar(20.0)
    inicio_do_upload = rede.espiado[0]
    assert inicio_do_upload["fase"] == sp.FASE_UPLOAD
    assert inicio_do_upload["download"] > 0


def test_upload_nao_pisca_com_o_numero_do_download():
    """A parcial da fase anterior tem que morrer junto com a fase.

    Sem isso, o tile de Upload abria mostrando a velocidade do DOWNLOAD em cinza
    com "medindo…": numero errado no lugar errado, justamente na tela em que a
    pessoa esta' conferindo numeros.
    """
    rede = RedeDirigida()
    motor = _motor(rede, urls_download=("https://dl/a",), urls_upload=("https://ul/b",))
    motor.start()
    assert motor.aguardar(20.0)
    assert not rede.espiado[0]["parcial"]


def test_falha_do_download_aparece_antes_do_fim_do_teste():
    """A falha ficava presa numa variavel local ate o encerramento.

    Enquanto isso o usuario passava a fase de upload inteira olhando um tile vazio
    e um badge dizendo alegremente "medindo o upload…".
    """
    rede = RedeDirigida({"dl": _429()})
    motor = _motor(rede, urls_download=("https://dl/a",), urls_upload=("https://ul/b",))
    motor.start()
    assert motor.aguardar(20.0)
    inicio_do_upload = rede.espiado[0]
    assert inicio_do_upload["erro"] is not None
    assert "esperar" in inicio_do_upload["erro"]


def test_maioria_dos_fluxos_derrubada_nao_vira_medicao_baixa():
    """O defeito mais perigoso do modulo: medicao falsa em vez de erro honesto.

    O 429 estoura no meio da rajada de pedidos paralelos e mata alguns fluxos,
    nao todos. Com tres de quatro mortos e um vivo, a fase rodava inteira com um
    quarto da banda e devolvia ~150 Mbps num link de 600, sem aviso nenhum, e o
    usuario acreditava no numero e ia reclamar da operadora.
    """
    class SoUmSobrevive(RedeDirigida):
        def __init__(self):
            super().__init__()
            self.mortos = 0

        def baixar(self, url, cancelado, contar, timeout):
            with self._trava:
                self.mortos += 1
                cair = self.mortos <= 3
            if cair:
                raise _429()
            while not cancelado():
                contar(self.por_chamada)
                time.sleep(0.01)

    rede = SoUmSobrevive()
    motor = _motor(rede, fluxos=4, urls_download=("https://dl/a",),
                   urls_upload=("https://ul/b",))
    motor.start()
    assert motor.aguardar(20.0)
    s = motor.snapshot()
    assert s["download"] is None, "medida com 3 de 4 fluxos mortos passou por boa"
    assert "esperar" in s["aviso"]


def test_fluxo_que_cai_uma_vez_e_reaberto(monkeypatch):
    """Fluxo morto e nao reposto mede menos banda do que o link tem.

    Um tropeco isolado (RST no meio da rajada) nao pode custar um quarto da
    medicao pelo resto da fase; o fluxo volta, com recuo, e o numero fecha limpo.
    """
    monkeypatch.setattr(sp, "RECUO_S", 0.02)

    class TropecaUmaVez(RedeDirigida):
        def __init__(self):
            super().__init__()
            self.aberturas = 0

        def baixar(self, url, cancelado, contar, timeout):
            with self._trava:
                self.aberturas += 1
                cair = self.aberturas <= 2
            if cair:
                raise ConnectionResetError("RST no meio da rajada")
            while not cancelado():
                contar(self.por_chamada)
                time.sleep(0.01)

    rede = TropecaUmaVez()
    motor = _motor(rede, fluxos=2, duracao=0.6, urls_download=("https://dl/a",),
                   urls_upload=("https://ul/b",))
    motor.start()
    assert motor.aguardar(20.0)
    s = motor.snapshot()
    assert s["download"] > 0
    assert rede.aberturas > 2, "o fluxo que caiu nunca foi reaberto"
    assert s["aviso"] is None                 # ninguem desistiu: medida limpa


def test_barra_nao_volta_ao_trocar_de_servidor():
    """Cada tentativa reinicia o relogio da fase; a barra nao pode reiniciar junto.

    Barra andando para tras e' sinal classico de bug, e acontecia justo no caminho
    de falha, quando o usuario ja' esta' desconfiado da demora.
    """
    rede = RedeDirigida({"lento": TimeoutError()}, demora=0.25)
    motor = _motor(rede, duracao=0.4,
                   urls_download=("https://lento/a", "https://bom/b"),
                   urls_upload=("https://bom/c",))
    motor.start()
    lidos = []
    while motor.rodando:
        lidos.append(motor.snapshot()["progresso"])
        time.sleep(0.005)
    motor.aguardar(20.0)
    assert lidos == sorted(lidos), "a barra andou para tras na troca de servidor"
    assert motor.snapshot()["download"] > 0


def test_upload_tambem_tem_fila():
    """Antes o envio dependia de um endpoint so': se ele tropecava, sumia o numero."""
    rede = RedeDirigida({"up1": _429()})
    motor = _motor(rede, urls_download=("https://dl/a",),
                   urls_upload=("https://up1/x", "https://up2/y"))
    motor.start()
    assert motor.aguardar(20.0)
    s = motor.snapshot()
    assert s["upload"] > 0
    assert "reserva" in s["aviso"]


def test_cancelar_para_sem_publicar_medida_pela_metade():
    """Cancelou no meio do download: nao existe numero fechado para mostrar."""
    motor = _motor(RedeFalsa(), duracao=30.0)
    motor.start()
    esperar_fase(motor, sp.FASE_DOWNLOAD)
    motor.cancel()
    assert motor.aguardar(10.0), "cancelar deixou o motor rodando"
    s = motor.snapshot()
    assert s["fase"] == sp.FASE_CANCELADO
    assert s["download"] is None
    assert s["rodando"] is False
    assert s["ping"] == 15.0            # o que ja' tinha fechado continua valendo


def test_stop_nao_deixa_thread_pendurada():
    """Fechar o app no meio do teste nao pode segurar o processo vivo."""
    antes = set(threading.enumerate())
    motor = _motor(RedeFalsa(), duracao=30.0)
    motor.start()
    esperar_fase(motor, sp.FASE_DOWNLOAD)
    motor.stop(5.0)
    assert motor.rodando is False
    sobrando = [t for t in threading.enumerate()
                if t not in antes and t.name.startswith(("speed", "speedtest"))]
    assert sobrando == []


def esperar_fase(motor, fase, limite=10.0):
    fim = time.monotonic() + limite
    while time.monotonic() < fim:
        if motor.snapshot()["fase"] == fase:
            return
        time.sleep(0.01)
    pytest.fail(f"o motor nunca chegou na fase {fase}")


def esperar_ate(condicao, limite=5.0, recado="condição nunca aconteceu"):
    fim = time.monotonic() + limite
    while time.monotonic() < fim:
        if condicao():
            return
        time.sleep(0.005)
    pytest.fail(recado)


# ── numero falso: migalha de byte nao pode virar medicao ─────────────────────
def test_link_que_solta_migalha_depois_do_aquecimento_nao_publica_zero():
    """Fim a fim do buraco do 0.0: servidor que aceita e entrega um byte.

    A conta era feita em bytes, mas quem convertia arredondava para duas casas:
    um byte depois do aquecimento virava exatamente 0.0, e dai' para a frente
    ninguem mais perguntava: `_rodar_fila` e `_concluir` so' testavam `is None`.
    O resultado era fase=pronto, erro=None, aviso=None, badge VERDE e "0.0 Mbps"
    na tela, para um link que na pratica esta' morto.
    """
    class Tarpit(RedeDirigida):
        def _correr(self, fase, url, cancelado, contar):
            with self._trava:
                self.chamadas.append((fase, sp._host(url)))
            time.sleep(0.2)          # fica quieta durante o aquecimento
            contar(1)                # ... e solta UM byte depois dele
            while not cancelado():
                time.sleep(0.01)

    rede = Tarpit()
    motor = _motor(rede, fluxos=2, duracao=0.5,
                   urls_download=("https://dl/a",), urls_upload=("https://ul/b",))
    motor.start()
    assert motor.aguardar(20.0)
    s = motor.snapshot()
    assert s["download"] is None and s["upload"] is None
    assert units.mbps(s["download"]) == units.DASH, "a tela escreveria 0.0 Mbps"
    assert s["fase"] == sp.FASE_ERRO
    assert s["quando"] is None, "medição que não aconteceu ganhou horário"
    assert "não enviou dados" in s["erro"]


# ── rajada de requisicoes: resposta vazia nao pode virar tempestade ──────────
class _RespostaCurta(RedeDirigida):
    """Servidor que responde 200 na hora e entrega quase nada.

    Content-Length: 0, um 204 ou o objeto cortado por limite de volume: nenhum
    deles levanta excecao, entao nenhum fluxo era contado como morto.
    """

    def __init__(self, bytes_por_resposta=0) -> None:
        super().__init__()
        self.aberturas = 0
        self.bytes_por_resposta = bytes_por_resposta

    def _abrir_e_fechar(self, contar):
        with self._trava:
            self.aberturas += 1
        if self.bytes_por_resposta:
            contar(self.bytes_por_resposta)

    def baixar(self, url, cancelado, contar, timeout):
        self._abrir_e_fechar(contar)

    def enviar(self, url, cancelado, contar, timeout, tamanho):
        self._abrir_e_fechar(contar)


def test_corpo_vazio_nao_vira_rajada_de_requisicoes(monkeypatch):
    """O caminho de SUCESSO nao tinha piso nenhum: entregou nada, reabre na hora.

    Medido antes do conserto: 10.131.329 aberturas em 2 s de fases com 4 fluxos.
    Com sockets de verdade isso e' uma tempestade de TCP+TLS contra o provedor:
    o app fabricando sozinho o HTTP 429 por volume que a fila inteira existe para
    evitar, e quatro threads em giro de CPU maxima dentro de um app de
    MONITORAMENTO, contaminando os proprios numeros da tela.
    """
    monkeypatch.setattr(sp, "RECUO_S", 0.01)
    rede = _RespostaCurta()
    motor = _motor(rede, fluxos=4, duracao=1.0,
                   urls_download=("https://dl/a",), urls_upload=("https://ul/b",))
    motor.start()
    assert motor.aguardar(20.0)
    s = motor.snapshot()
    teto = 4 * 3 * 2        # fluxos x tentativas x fases
    assert rede.aberturas <= teto, f"{rede.aberturas} aberturas em 2 fases"
    assert s["download"] is None and s["upload"] is None
    assert s["fase"] == sp.FASE_ERRO
    assert "não enviou dados" in s["erro"]


def test_resposta_minuscula_nao_vira_medicao_da_propria_reconexao(monkeypatch):
    """Pior que a rajada: a rajada com bytes contados.

    Pagina de erro de proxy ou portal cativo (1500 B) devolvia 200 e uns bytes; o
    motor somava tudo e publicava 2,4 Mbps de download com badge verde. Esse
    numero nao mede link nenhum; mede quantas vezes por segundo a maquina
    consegue reabrir uma conexao.
    """
    monkeypatch.setattr(sp, "RECUO_S", 0.01)
    rede = _RespostaCurta(bytes_por_resposta=1500)
    motor = _motor(rede, fluxos=4, duracao=1.0,
                   urls_download=("https://dl/a",), urls_upload=("https://ul/b",))
    motor.start()
    assert motor.aguardar(20.0)
    s = motor.snapshot()
    assert rede.aberturas <= 4 * 3 * 2, f"{rede.aberturas} aberturas em 2 fases"
    assert s["download"] is None and s["upload"] is None
    assert s["fase"] == sp.FASE_ERRO


def test_arquivo_que_acaba_continua_sendo_reaberto(monkeypatch):
    """O piso nao pode matar o motivo de existir da reabertura.

    Num link rapido o arquivo do servidor acaba antes do relogio da fase; sem
    reabrir, a segunda metade da janela seria medida como zero.
    """
    monkeypatch.setattr(sp, "RECUO_S", 0.01)

    class ArquivoCurto(RedeDirigida):
        def __init__(self):
            super().__init__()
            self.aberturas = 0

        def _correr(self, fase, url, cancelado, contar):
            with self._trava:
                self.aberturas += 1
            for _ in range(4):              # 8 MB e o corpo acaba
                if cancelado():
                    return
                contar(2_000_000)
                time.sleep(0.01)

    rede = ArquivoCurto()
    motor = _motor(rede, fluxos=2, duracao=0.5,
                   urls_download=("https://dl/a",), urls_upload=("https://ul/b",))
    motor.start()
    assert motor.aguardar(20.0)
    s = motor.snapshot()
    assert rede.aberturas > 4, "o fluxo parou de reabrir e mediria metade da janela"
    assert s["download"] > 0 and s["upload"] > 0
    assert s["aviso"] is None


# ── cancelamento: quem cancela nao pode ser quem congela ─────────────────────
class _ServidorLocal:
    """Servidor de mentira em 127.0.0.1; nenhum byte sai da máquina.

    `resposta=None` e' o mudo de proposito: aceita a conexao e nunca responde. E'
    o caso em que o fluxo fica preso DENTRO do urlopen, antes de existir qualquer
    objeto para cancelar.
    """

    def __init__(self, resposta: bytes | None = None) -> None:
        self._srv = socket.socket()
        self._srv.bind(("127.0.0.1", 0))
        self._srv.listen(8)
        self.porta = self._srv.getsockname()[1]
        self.aceitas = 0
        self._resposta = resposta
        self._clientes: list = []
        threading.Thread(target=self._servir, daemon=True, name="servidor-falso").start()

    def _servir(self) -> None:
        while True:
            try:
                cliente, _ = self._srv.accept()
            except OSError:
                return
            self._clientes.append(cliente)
            self.aceitas += 1
            if self._resposta is not None:
                try:
                    cliente.sendall(self._resposta)
                except OSError:
                    pass

    def url(self, caminho: str = "/arquivo.bin") -> str:
        return f"http://127.0.0.1:{self.porta}{caminho}"

    def fechar(self) -> None:
        self._srv.close()
        for c in self._clientes:
            try:
                c.close()
            except OSError:
                pass


def _puxar_em_thread(rede, url, timeout=30.0):
    """Baixa numa thread e avisa quando voltou. Timeout alto de proposito: se o
    cancelamento nao funcionar, quem falha e' o teste, e nao o relogio do socket."""
    fim = threading.Event()

    def correr():
        try:
            rede.baixar(url, lambda: False, lambda n: None, timeout)
        except Exception:  # noqa: BLE001, o que importa e' ter voltado
            pass
        fim.set()

    threading.Thread(target=correr, daemon=True, name="leitor-falso").start()
    return fim


def test_cancelar_nao_congela_quem_chamou_com_o_socket_travado():
    """O congelamento da interface: `close()` num HTTPResponse pega a trava do
    buffer, e a trava fica com a thread que esta' dentro do `read()`.

    Com o socket empacado (link que caiu, VPN que virou, exatamente quando se
    clica em Cancelar), esse close so' voltava no timeout do socket: 9,01 s
    medidos com os padroes de producao, ~75 quadros do timer perdidos e a janela
    em "Não Respondendo". O bloqueio nao sumia, apenas mudava da thread de
    trabalho para a da interface, que e' quem chama `cancel()` e `stop()`.
    """
    servidor = _ServidorLocal(b"HTTP/1.1 200 OK\r\nContent-Length: 90000000\r\n\r\n"
                              + b"x" * 4096)
    try:
        rede = sp.Rede()
        fim = _puxar_em_thread(rede, servidor.url())
        esperar_ate(lambda: servidor.aceitas >= 1, recado="o servidor nunca foi procurado")
        time.sleep(0.25)                    # o read ja' esta' dentro da trava
        inicio = time.perf_counter()
        rede.abortar()
        gasto = time.perf_counter() - inicio
        assert gasto < 0.5, f"abortar() segurou quem chamou por {gasto:.2f} s"
        assert fim.wait(3.0), "o read travado nunca foi solto"
    finally:
        servidor.fechar()


def test_cancelar_alcanca_o_fluxo_preso_antes_da_primeira_resposta():
    """Fluxo parado no TTFB era invisivel ao cancelamento.

    A resposta so' entrava na lista de abertos DEPOIS que o urlopen voltava;
    durante connect, TLS e espera do primeiro byte nao havia nada para derrubar.
    A orfa sobrevivia ao fim da fase e ia consumir link no meio da medicao
    seguinte.
    """
    servidor = _ServidorLocal(None)         # aceita e nunca responde
    try:
        rede = sp.Rede()
        fim = _puxar_em_thread(rede, servidor.url())
        esperar_ate(lambda: servidor.aceitas >= 1, recado="o servidor nunca foi procurado")
        time.sleep(0.1)
        inicio = time.perf_counter()
        rede.abortar()
        assert time.perf_counter() - inicio < 0.5
        assert fim.wait(3.0), "o fluxo continuou preso dentro do urlopen"
    finally:
        servidor.fechar()


def test_cancelar_nao_espera_transporte_que_demora_a_fechar():
    """Ate' o caso desconhecido sai da frente: o close vai para outra thread."""
    class FechaDevagar:
        def __init__(self):
            self.fechou = threading.Event()

        def close(self):
            time.sleep(1.0)
            self.fechou.set()

    rede = sp.Rede()
    lerdo = FechaDevagar()
    rede._abertos.add(lerdo)
    inicio = time.perf_counter()
    rede.abortar()
    assert time.perf_counter() - inicio < 0.3
    assert lerdo.fechou.wait(3.0), "ninguém chegou a fechar o transporte"


# ── orfas: fim de fase precisa ser fim de verdade ────────────────────────────
class _Grudenta(RedeDirigida):
    """Fluxo que ignora o cancelamento por um tempo, o mesmo que um socket
    empacado dentro do urlopen faz na vida real."""

    def __init__(self, vida=0.6) -> None:
        super().__init__()
        self.vida = vida
        self.dl_ativos = 0
        self.upload_com_download_no_ar = 0

    def baixar(self, url, cancelado, contar, timeout):
        with self._trava:
            self.chamadas.append(("download", sp._host(url)))
            self.dl_ativos += 1
        try:
            fim = time.monotonic() + self.vida
            while time.monotonic() < fim:
                contar(self.por_chamada)
                time.sleep(0.01)
        finally:
            with self._trava:
                self.dl_ativos -= 1

    def enviar(self, url, cancelado, contar, timeout, tamanho):
        with self._trava:
            if self.dl_ativos:
                self.upload_com_download_no_ar += 1
        self._correr("upload", url, cancelado, contar)


def test_aguardar_nao_diz_que_acabou_com_fluxo_ainda_no_ar(monkeypatch):
    """`aguardar()` so' conhecia o motor, nunca os fluxos.

    Depois de `stop(30 s)` o motor reportava fim com quatro threads vivas e os
    sockets de pe'; quem chamou para fechar o app acreditava que estava tudo
    parado. Agora o True significa "acabou", e o False e' informacao util.
    """
    monkeypatch.setattr(sp, "JOIN_TOTAL_S", 0.05)
    rede = _Grudenta(vida=1.0)
    motor = _motor(rede, fluxos=2, duracao=0.2,
                   urls_download=("https://dl/a",), urls_upload=("https://ul/b",))
    motor.start()
    # Esperar a FASE nao basta: ela e' publicada antes de o primeiro fluxo subir,
    # e cancelar nessa fresta acabaria testando o caso em que nao ha' fluxo algum.
    esperar_ate(lambda: rede.dl_ativos >= 1, recado="os fluxos nunca subiram")
    motor.cancel()
    assert motor.aguardar(0.3) is False, "disse que acabou com os fluxos ainda vivos"
    assert [t for t in threading.enumerate() if t.name.startswith("speed-")], \
        "cenário não reproduziu: nenhum fluxo estava vivo"
    assert motor.aguardar(5.0) is True
    assert not [t for t in threading.enumerate() if t.name.startswith("speed-")]


def test_upload_medido_com_download_no_ar_sai_com_ressalva(monkeypatch):
    """Orfa atravessando a fronteira de fase: upload medido com o link ocupado.

    O orcamento de encerramento caia para 50 ms por fluxo assim que o prazo
    passava, e a fase seguinte comecava com os fluxos anteriores ainda baixando.
    O upload saia abaixo do real (sem uma palavra), que e' o mesmo tipo de
    defeito que a regra dos fluxos mortos existe para matar.
    """
    monkeypatch.setattr(sp, "JOIN_TOTAL_S", 0.05)
    rede = _Grudenta(vida=0.6)
    motor = _motor(rede, fluxos=2, duracao=0.2,
                   urls_download=("https://dl/a",), urls_upload=("https://ul/b",))
    motor.start()
    assert motor.aguardar(20.0)
    s = motor.snapshot()
    assert rede.upload_com_download_no_ar, \
        "cenário não reproduziu: o upload não pegou download no ar"
    assert s["upload"] > 0
    assert "fase anterior" in (s["aviso"] or ""), \
        "upload medido com o link ocupado saiu como medida limpa"


def test_fim_de_fase_espera_os_fluxos_antes_da_proxima():
    """No caso normal (socket derrubado responde ao cancelamento), a fase seguinte
    comeca com o link livre, e nao ha' ressalva nenhuma a dar."""
    rede = _Grudenta(vida=0.05)
    motor = _motor(rede, fluxos=2, duracao=0.3,
                   urls_download=("https://dl/a",), urls_upload=("https://ul/b",))
    motor.start()
    assert motor.aguardar(20.0)
    s = motor.snapshot()
    assert rede.upload_com_download_no_ar == 0
    assert s["download"] > 0 and s["upload"] > 0
    assert s["aviso"] is None


# ── mensagens da fila: a conclusao certa da evidencia reunida ────────────────
def test_fila_inteira_muda_nao_culpa_o_servidor_de_teste():
    """Quatro provedores, em redes independentes, calados, e um upload de pé.

    Esta e' a evidencia mais forte possivel de que o link de quem mede e' que
    esta' ruim, e o texto antigo escrevia, no singular, "o servidor de teste NÃO
    respondeu a tempo", ao lado de um numero de upload medido com sucesso na
    mesma tela.
    """
    hosts = ("um", "dois", "tres", "quatro")
    rede = RedeDirigida({h: urllib.error.URLError(TimeoutError()) for h in hosts})
    motor = _motor(rede, urls_download=tuple(f"https://{h}/a" for h in hosts),
                   urls_upload=("https://ul/b",))
    motor.start()
    assert motor.aguardar(20.0)
    s = motor.snapshot()
    assert s["upload"] > 0                      # a internet funciona, e a tela mostra
    aviso = s["aviso"]
    assert "4 servidores" in aviso
    assert "sua conexão" in aviso
    assert "o servidor de teste não respondeu" not in aviso


def test_fila_que_recusou_com_codigo_nao_vira_nenhum_respondeu():
    """404 em toda a fila: responderam, e com um codigo. Dizer o contrario manda
    o usuario procurar defeito na propria internet."""
    def _404():
        return urllib.error.HTTPError("u", 404, "Not Found", {}, None)

    rede = RedeDirigida({"um": _404(), "dois": _404()})
    motor = _motor(rede, urls_download=("https://um/a", "https://dois/b"),
                   urls_upload=("https://ul/c",))
    motor.start()
    assert motor.aguardar(20.0)
    aviso = motor.snapshot()["aviso"]
    assert "responderam" in aviso and "404" in aviso
    assert "não respondeu" not in aviso


def test_transferencia_que_cai_em_todos_os_servidores_aponta_a_conexao():
    """Os quatro entregaram bytes e metade dos fluxos caiu em todos.

    A medida e' descartada (certissimo), mas a frase dizia "nenhum dos 4
    servidores de teste respondeu", quando todos responderam E transferiram. O
    que esta' derrubando as transferencias e' a conexao de quem mede, e era
    exatamente isso que nao era dito.
    """
    class MetadeCai(RedeDirigida):
        def baixar(self, url, cancelado, contar, timeout):
            with self._trava:
                self.chamadas.append(("download", sp._host(url)))
                cair = len(self.chamadas) % 2
            contar(3_000_000)                   # a casa respondeu E mandou dados
            if cair:
                raise ConnectionResetError("a transferência caiu no meio")
            while not cancelado():
                contar(self.por_chamada)
                time.sleep(0.01)

    hosts = ("um", "dois", "tres", "quatro")
    rede = MetadeCai()
    motor = _motor(rede, fluxos=4, tentativas=1,
                   urls_download=tuple(f"https://{h}/a" for h in hosts),
                   urls_upload=("https://ul/b",))
    motor.start()
    assert motor.aguardar(30.0)
    s = motor.snapshot()
    assert s["download"] is None                # descartar continua certo
    aviso = s["aviso"]
    assert "enviaram dados" in aviso
    assert "sua conexão" in aviso
    assert "não responderam" not in aviso


# ── escolha automatica do servidor ───────────────────────────────────────────
def _prov(host, envio=False, **kw):
    return sp.Provedor(f"https://{host}/down",
                       envio=f"https://{host}/up" if envio else "", **kw)


def test_fila_e_remontada_pela_latencia_medida():
    """O coração da escolha automática: a ordem da semente é só um palpite.

    Antes, a fila era fixa e o teste media pelo primeiro que aceitasse: se o
    servidor da frente ficasse a 130 ms, era ele que media, e o número saía a um
    oitavo do real sem ninguém perguntar se havia coisa melhor na lista.
    """
    escolha = sp.escolher((_prov("longe"), _prov("perto")), (),
                          {"longe": 130.0, "perto": 12.4})
    assert escolha.servidor.host == "perto"
    assert escolha.latencia_ms == 12.4
    assert [p.host for p in escolha.download] == ["perto", "longe"]


def test_escolha_prefere_quem_mede_as_duas_fases_no_mesmo_lugar():
    """Medido: Cachefly 15,3 ms só desce; Cloudflare 15,8 ms desce E sobe.

    Meio milissegundo não paga o preço de a tela anunciar "via Cachefly" e o
    número de upload ter vindo de outra casa; quem for conferir é enganado por
    um campo que parece exato.
    """
    cdn, completo = _prov("cachefly"), _prov("cloudflare", envio=True)
    escolha = sp.escolher((cdn, completo), (sp._como_upload(completo),),
                          {"cachefly": 15.3, "cloudflare": 15.8})
    assert escolha.servidor.host == "cloudflare"
    assert escolha.download[0].host == "cloudflare"
    assert escolha.upload[0].host == "cloudflare"
    assert "cachefly" in [p.host for p in escolha.download]      # reserva continua


def test_empate_de_latencia_mantem_a_ordem_da_semente():
    """Sem casa nenhuma medida (ou todas iguais) a semente é que decide, e ela
    foi escolhida a dedo, com número. Reordenar por acaso jogaria isso fora."""
    fila = (_prov("um"), _prov("dois"), _prov("tres"))
    escolha = sp.escolher(fila, (), {"um": 16.0, "dois": 16.0, "tres": 16.0})
    assert [p.host for p in escolha.download] == ["um", "dois", "tres"]


def test_casa_muda_vai_para_o_fim_da_fila_em_vez_de_sumir():
    """Sonda perdida não é prova de servidor morto: pode ter sido um pacote.

    Descartar quem não respondeu deixaria a fila vazia numa rede que bloqueia
    connect solto, e fila vazia mede menos que fila duvidosa.
    """
    escolha = sp.escolher((_prov("mudo"), _prov("vivo")), (),
                          {"mudo": None, "vivo": 20.0})
    assert [p.host for p in escolha.download] == ["vivo", "mudo"]
    assert escolha.responderam == 1 and escolha.sondados == 2


def test_ninguem_respondeu_ainda_devolve_uma_fila_para_tentar():
    """Todas mudas: o teste continua, e é o download que decide se há internet."""
    escolha = sp.escolher((_prov("um"), _prov("dois")), (),
                          {"um": None, "dois": None})
    assert [p.host for p in escolha.download] == ["um", "dois"]
    assert escolha.latencia_ms is None


def test_fila_escolhida_tem_teto_de_tamanho():
    """A lista pública tem 22 casas. Sem teto, um dia ruim seriam 22 tentativas
    de 6 s cada: dois minutos de "medindo…" para não medir nada."""
    fila = tuple(_prov(f"h{i}") for i in range(10))
    escolha = sp.escolher(fila, (), {f"h{i}": float(i + 10) for i in range(10)})
    assert len(escolha.download) == sp.FILA_MAXIMA
    assert escolha.download[0].host == "h0"


def test_servidor_fixado_ganha_da_medicao_e_mantem_reserva():
    """Vontade declarada ganha de latência, mas fixar não pode ser o mesmo que
    ficar sem teste no dia em que aquela casa estiver fora do ar."""
    escolha = sp.escolher((_prov("rapido"), _prov("preferido")), (),
                          {"rapido": 10.0, "preferido": 90.0}, fixado="preferido")
    assert escolha.servidor.host == "preferido"
    assert escolha.fixado is True
    assert [p.host for p in escolha.download] == ["preferido", "rapido"]


def test_servidor_fixado_que_sumiu_da_lista_nao_trava_o_teste():
    """Host gravado meses atrás que não existe mais volta ao automático."""
    escolha = sp.escolher((_prov("um"),), (), {"um": 16.0}, fixado="fantasma")
    assert escolha.servidor.host == "um"
    assert escolha.fixado is False


# ── lista publica de servidores ──────────────────────────────────────────────
_ITEM = {"name": "Atlanta", "server": "//speedtest.example.net/",
         "dlURL": "backend/garbage.php", "ulURL": "backend/empty.php"}


def test_lista_publica_normaliza_o_endereco_e_descarta_lixo():
    """Dois detalhes medidos na lista real: `server` às vezes vem sem esquema
    ("//host/") e o caminho pode ser na raiz ou em /backend conforme a
    instalação. Item quebrado é ignorado: veio da internet, não há o que fazer."""
    provs = sp.provedores_da_lista([_ITEM, {"server": "https://x/"}, "lixo", 42])
    assert len(provs) == 1
    assert provs[0].url == "https://speedtest.example.net/backend/garbage.php"
    assert provs[0].envio == "https://speedtest.example.net/backend/empty.php"
    assert provs[0].nome == "Atlanta"


def test_servidor_da_lista_publica_nunca_se_apresenta_como_perto():
    """Não há campo confiável de país na lista, e medido não há uma única casa
    brasileira nela: a mais perto é Atlanta, a 134 ms. Prometer proximidade que
    não existe é a mentira que este módulo inteiro existe para não contar."""
    assert sp.provedores_da_lista([_ITEM])[0].perto is False


class _RedeDeLista(sp.Rede):
    """Servidor de lista de mentira: responde o que mandarem, e anota o ETag."""

    def __init__(self, codigo=200, corpo="[]", etag="v1") -> None:
        super().__init__()
        self.codigo, self.corpo, self.etag = codigo, corpo, etag
        self.pedidos: list = []

    def texto(self, url, timeout, etag=None):
        self.pedidos.append(etag)
        return self.codigo, self.corpo, self.etag


def _sandbox(tmp_path, monkeypatch):
    """Estado em disco num diretório só deste teste."""
    monkeypatch.setenv("DBXSTATS_DATA_DIR", str(tmp_path))


def test_lista_e_guardada_em_disco_e_nao_e_pedida_de_novo(tmp_path, monkeypatch):
    """A lista muda em meses. Perguntar a cada teste seria gastar rede e tempo
    do usuário para receber o mesmo arquivo de sempre."""
    _sandbox(tmp_path, monkeypatch)
    rede = _RedeDeLista(corpo=json.dumps([_ITEM]))
    assert sp.atualizar_lista(rede) == 1
    assert [p.host for p in sp.lista_em_cache()] == ["speedtest.example.net"]
    assert sp.atualizar_lista(rede) == 0
    assert len(rede.pedidos) == 1, "pediu a lista de novo com o cache fresco"


def test_lista_sem_novidade_renova_a_validade_com_o_etag(tmp_path, monkeypatch):
    """304 custa ~300 bytes contra os 6.115 da resposta cheia, e o cache não
    pode ser apagado por uma resposta que justamente diz "nada mudou"."""
    _sandbox(tmp_path, monkeypatch)
    sp.atualizar_lista(_RedeDeLista(corpo=json.dumps([_ITEM]), etag="v1"))
    sp.gravar_estado({"lista_quando": time.time() - sp.LISTA_TTL_S - 1})
    assert sp.lista_vencida() is True

    rede = _RedeDeLista(codigo=304, corpo="")
    assert sp.atualizar_lista(rede) == 0
    assert rede.pedidos == ["v1"], "não mandou o ETag que já tinha"
    assert sp.lista_vencida() is False
    assert len(sp.lista_em_cache()) == 1, "o 304 apagou a lista que já estava boa"


def test_lista_que_nao_responde_nao_atrapalha_ninguem(tmp_path, monkeypatch):
    """Sem lista o app mede com a semente embutida, que é o que ele fazia antes
    de existir lista nenhuma. Falhar o teste por causa disso seria trocar um
    bônus por um defeito."""
    _sandbox(tmp_path, monkeypatch)

    class Muda(sp.Rede):
        def texto(self, url, timeout, etag=None):
            raise TimeoutError("nem responde")

    assert sp.atualizar_lista(Muda()) == 0
    assert sp.lista_em_cache() == ()


def test_lista_em_formato_estranho_nao_vira_excecao(tmp_path, monkeypatch):
    _sandbox(tmp_path, monkeypatch)
    assert sp.atualizar_lista(_RedeDeLista(corpo="<html>não sou json</html>")) == 0
    assert sp.atualizar_lista(_RedeDeLista(corpo='{"servidores": []}')) == 0
    assert sp.lista_em_cache() == ()


def test_servidor_fixado_sobrevive_ao_fechar_o_app(tmp_path, monkeypatch):
    _sandbox(tmp_path, monkeypatch)
    assert sp.servidor_fixado() is None
    sp.fixar_servidor("speed.cloudflare.com")
    assert sp.servidor_fixado() == "speed.cloudflare.com"
    sp.fixar_servidor(None)
    assert sp.servidor_fixado() is None


def test_estado_corrompido_nao_impede_o_app_de_medir(tmp_path, monkeypatch):
    """JSON truncado por queda de energia é arquivo, não sentença."""
    _sandbox(tmp_path, monkeypatch)
    (tmp_path / sp.ARQUIVO_ESTADO).write_text("{isto não fecha", encoding="utf-8")
    assert sp.ler_estado() == {}
    assert sp.servidor_fixado() is None
    assert sp.lista_em_cache() == ()


# ── escolha automatica, fim a fim ────────────────────────────────────────────
def test_motor_mede_pelo_servidor_de_menor_latencia():
    """Fim a fim: quem sonda melhor é quem mede, e a tela diz quem foi."""
    rede = RedeDirigida(latencias={"longe": 130.0, "perto": 12.4})
    motor = _motor(rede, urls_download=("https://longe/a", "https://perto/b"),
                   urls_upload=("https://perto/c",))
    motor.start()
    assert motor.aguardar(20.0)
    s = motor.snapshot()
    assert s["servidor"] == "perto"
    assert s["servidor_ms"] == 12.4
    assert s["ping"] == 12.4, "o ping ficou do servidor errado"
    assert [h for f, h in rede.chamadas if f == "download"][0] == "perto"


def test_ping_e_jitter_saem_de_sondas_no_mesmo_servidor():
    """Jitter calculado com amostras de casas diferentes mede diversidade de
    caminho, não oscilação da rede, e pinta de instável uma conexão que oscila
    1 ms. A varredura compara casas; o ping descreve a conexão."""
    rede = RedeDirigida(latencias={"a": 90.0, "b": 20.0})
    motor = _motor(rede, sondas=4, urls_download=("https://a/x", "https://b/y"),
                   urls_upload=("https://b/z",))
    motor.start()
    assert motor.aguardar(20.0)
    s = motor.snapshot()
    assert s["ping"] == 20.0
    assert s["jitter"] == 0.0, "misturou sondas de servidores diferentes"


def test_motor_respeita_o_servidor_fixado_pelo_usuario():
    rede = RedeDirigida(latencias={"rapido": 10.0, "meu": 40.0})
    motor = _motor(rede, urls_download=("https://rapido/a", "https://meu/b"),
                   urls_upload=("https://meu/c",))
    motor.fixar("meu")
    motor.start()
    assert motor.aguardar(20.0)
    s = motor.snapshot()
    assert s["servidor"] == "meu"
    assert s["fixado"] == "meu"
    assert [h for f, h in rede.chamadas if f == "download"][0] == "meu"


def test_a_tela_diz_qual_casa_mediu_o_upload():
    """O campo que enganava: `servidor` era preenchido só na fase de download,
    então o relatório dizia "via fulano" sem nunca contar de onde veio o upload,
    e as duas fases podem perfeitamente estar em casas diferentes."""
    rede = RedeDirigida()
    motor = _motor(rede, urls_download=("https://dl/a",), urls_upload=("https://ul/b",))
    motor.start()
    assert motor.aguardar(20.0)
    s = motor.snapshot()
    assert s["servidor"] == "dl"
    assert s["servidor_envio"] == "ul"


def test_a_busca_da_lista_publica_nao_segura_o_teste(tmp_path, monkeypatch):
    """A regra que evita o pior dos dois mundos: o teste de hoje anda com o que
    já está no disco, e o que chegar agora só enriquece o de amanhã. Esperar
    seria atrasar a medição para acrescentar candidatos a 134 ms."""
    _sandbox(tmp_path, monkeypatch)

    class Lerda(RedeDirigida):
        def texto(self, url, timeout, etag=None):
            time.sleep(5.0)
            raise TimeoutError("lista lerda")

    rede = Lerda()
    motor = _motor(rede, lista_publica=True, urls_download=("https://dl/a",),
                   urls_upload=("https://ul/b",))
    inicio = time.monotonic()
    motor.start()
    assert motor.aguardar(20.0)
    assert time.monotonic() - inicio < 3.0, "o teste esperou a lista de servidores"
    assert motor.snapshot()["download"] > 0


def test_lista_em_disco_entra_como_candidata_no_proximo_teste(tmp_path, monkeypatch):
    """Para que serve guardar a lista: no teste seguinte a casa nova é sondada
    junto com a semente, e ganha se for melhor."""
    _sandbox(tmp_path, monkeypatch)
    sp.gravar_estado({"lista": [{"name": "Vizinha", "server": "https://vizinha/",
                                 "dlURL": "garbage.php", "ulURL": "empty.php"}],
                      "lista_quando": time.time()})
    rede = RedeDirigida(latencias={"semente": 40.0, "vizinha": 8.0})
    motor = _motor(rede, lista_publica=True, urls_download=("https://semente/a",),
                   urls_upload=("https://semente/b",))
    motor.start()
    assert motor.aguardar(20.0)
    s = motor.snapshot()
    assert s["servidor"] == "vizinha"
    assert s["candidatos"] == 2


def test_servidor_fora_do_pais_avisa_mesmo_sendo_o_primeiro_da_fila():
    """Antes a ressalva só saía quando a casa distante era reserva. Com escolha
    automática e lista pública (que não tem uma casa brasileira sequer), a casa
    distante pode ser a primeira, e aí o número baixo sairia sem explicação."""
    rede = RedeDirigida()
    motor = _motor(rede, urls_download=(sp.Provedor("https://longe/a", perto=False),),
                   urls_upload=("https://ul/b",))
    motor.start()
    assert motor.aguardar(20.0)
    s = motor.snapshot()
    assert s["download"] > 0
    assert "fora do país" in s["aviso"]


# ── upload: a janela de envio e os tetos honestos ────────────────────────────
def test_teto_da_janela_reproduz_o_defeito_medido():
    """A conta que explica os 118,5 Mbps: 65536 x 8 / 0,016 = 32,8 Mbps por
    fluxo, 131 com quatro. Não é a banda do link, é o buffer dividido pelo RTT."""
    assert sp.teto_da_janela(65536, 16.0, 4) == pytest.approx(131.07, abs=0.1)
    assert sp.teto_da_janela(4 << 20, 16.0, 4) > 8000
    assert sp.teto_da_janela(0, 16.0, 4) is None
    assert sp.teto_da_janela(65536, None, 4) is None


def test_teto_do_processo_e_medida_e_nao_estimativa():
    """Bytes movidos divididos pelo tempo de CPU que as threads gastaram: é o que
    este Python empurra com um núcleo."""
    assert sp.teto_do_processo(1_000_000_000, 0.59) == pytest.approx(13559, abs=1)
    assert sp.teto_do_processo(0, 1.0) is None
    assert sp.teto_do_processo(1000, 0.0) is None


def test_upload_pede_janela_de_envio_maior_no_socket_cru():
    """O conserto de uma linha, verificado onde ele acontece.

    Nenhum byte sai da máquina: o servidor é 127.0.0.1. O que se prova aqui é que
    o SO_SNDBUF é pedido ANTES do TLS, no socket recém-criado, e que o sistema
    concedeu bem mais que os 65536 padrão: o número que limitava o upload a um
    oitavo do link.
    """
    padrao = socket.socket().getsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF)
    servidor = _ServidorLocal(b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\n\r\n")
    try:
        rede = sp.Rede()
        rede.enviar(servidor.url("/up"), lambda: False, lambda n: None, 5.0, 50_000)
        concedido = rede.buffer_de_envio()
    finally:
        servidor.fechar()
    assert concedido >= 1 << 20, f"o sistema concedeu só {concedido} bytes de envio"
    assert concedido > padrao


def test_download_nao_mexe_na_janela_de_envio():
    """No download o Windows já auto-ajusta a janela de RECEPÇÃO sozinho; pedir
    buffer de envio ali seria enfeite com ar de conserto."""
    servidor = _ServidorLocal(b"HTTP/1.1 200 OK\r\nContent-Length: 4\r\n\r\nabcd")
    try:
        rede = sp.Rede()
        rede.baixar(servidor.url(), lambda: False, lambda n: None, 5.0)
        assert rede.buffer_de_envio() == 0
    finally:
        servidor.fechar()


def test_conexao_de_upload_escreve_em_blocos_grandes():
    """8 KB é o padrão do http.client e custa 3,01 s de CPU por GB contra 0,59 s
    com 64 KB. Não muda Mbps; muda quanto de núcleo um app de MONITORAMENTO
    queima enquanto mostra os próprios números na tela."""
    class Base:
        def __init__(self, host, **kw):
            self.recebido = kw

        def connect(self):
            pass

    conexao = sp._conexao_rastreada(Base, lambda s: None, None)("host")
    assert conexao.recebido["blocksize"] == sp.BLOCO


def test_buffer_de_envio_fica_com_o_fluxo_mais_apertado():
    """O teto da subida é ditado pelo pior socket, não pelo último a conectar."""
    rede = sp.Rede()
    rede._anotar_buffer(4 << 20)
    rede._anotar_buffer(65536)
    rede._anotar_buffer(1 << 20)
    assert rede.buffer_de_envio() == 65536
    rede.esquecer_buffer()
    assert rede.buffer_de_envio() == 0


class _ComBuffer(RedeDirigida):
    """Rede falsa que também finge o buffer de envio concedido pelo sistema."""

    def __init__(self, buffer_, **kw) -> None:
        super().__init__(**kw)
        self._buffer = buffer_

    def buffer_de_envio(self):
        return self._buffer


def test_upload_no_teto_da_janela_nao_e_apresentado_como_velocidade_do_link():
    """A promessa central: número que encostou no teto do envio deixou de falar
    sobre a internet. Reportar 118 Mbps calado foi exatamente o defeito que este
    módulo tinha: o app media a si mesmo e chamava de "sua velocidade"."""
    rede = _ComBuffer(65536, sonda=16.0)
    motor = _motor(rede, urls_download=("https://dl/a",), urls_upload=("https://ul/b",))
    motor.start()
    assert motor.aguardar(20.0)
    s = motor.snapshot()
    assert s["upload"] > 0
    assert s["teto_janela"] == pytest.approx(65.54, abs=0.1)   # 65536 x 8 x 2 / 0,016
    assert "teto da janela de envio" in s["aviso"]
    assert "Mbps" in s["aviso"], "disse que bateu no teto e escondeu o número"


def test_upload_com_folga_de_janela_nao_ganha_ressalva_nenhuma():
    """Ressalva falsa custa tanto quanto número falso: se o teto não morde, a
    medida é do link e não há nada a dizer."""
    rede = _ComBuffer(4 << 20, sonda=16.0)
    motor = _motor(rede, urls_download=("https://dl/a",), urls_upload=("https://ul/b",))
    motor.start()
    assert motor.aguardar(20.0)
    s = motor.snapshot()
    assert s["upload"] > 0
    assert s["teto_janela"] > 4000
    assert s["aviso"] is None


def test_janela_curta_com_buffer_grande_sai_com_ressalva():
    """A armadilha que nasce junto com o conserto: o contador soma o que foi
    entregue ao SOCKET. Com 4 MB por fluxo isso são megabytes que o servidor
    ainda não viu; em regime o excesso cancela, mas numa janela curta ele vira a
    medida inteira: medido, +323%."""
    rede = _ComBuffer(8 << 20, por_chamada=10_000, sonda=16.0)
    motor = _motor(rede, urls_download=("https://dl/a",), urls_upload=("https://ul/b",))
    motor.start()
    assert motor.aguardar(20.0)
    s = motor.snapshot()
    assert s["upload"] > 0
    assert "acima do real" in s["aviso"]


def test_ressalva_do_teto_do_app_diz_o_numero():
    """Quando o Python é o gargalo, a tela precisa dizer QUANTO ele aguenta, sem
    o número, "o app é o limite" não ajuda ninguém a decidir nada."""
    medida = sp._Medida(taxa=900.0, provedor=sp.Provedor("https://x/y"),
                        teto_processo=950.0)
    texto = " ".join(sp._ressalvas("Upload", medida))
    assert "teto deste app" in texto and "950 Mbps" in texto
    assert sp._ressalvas("Upload", medida._replace(teto_processo=9000.0)) == []


def test_teto_acima_de_mil_sai_em_gigabit():
    assert sp._texto_taxa(13559.0) == "13,6 Gbps"
    assert sp._texto_taxa(931.8) == "932 Mbps"


# ── a tela do teste ──────────────────────────────────────────────────────────
def _tela(tmp_path, monkeypatch):
    """Monta a tela de rede de verdade, sem janela e sem tocar no disco do app.

    Qt entra tarde e dentro da função de propósito: o resto deste arquivo mede o
    motor, que não depende de interface nenhuma, e não deveria pagar o preço de
    carregar a biblioteca gráfica para isso.
    """
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("DBXSTATS_DATA_DIR", str(tmp_path))
    from PySide6.QtWidgets import QApplication

    from dbxstats.config import Settings
    from dbxstats.core.series import Accumulator, History
    from dbxstats.ui.views import network

    QApplication.instance() or QApplication([])

    class _App:
        def __init__(self):
            self.settings = Settings()
            self.stats = Accumulator()
            self.history = History(60)

    return network, network.NetworkView(_App())


def test_a_tela_oferece_os_servidores_que_o_motor_usaria(tmp_path, monkeypatch):
    """Não adianta oferecer uma casa que o motor não conhece: a lista sai dele."""
    _, v = _tela(tmp_path, monkeypatch)
    try:
        assert v.test_srv.itemData(0) == ""              # automático é o padrão
        assert v.test_srv.currentIndex() == 0
        hosts = [v.test_srv.itemData(i) for i in range(1, v.test_srv.count())]
        assert hosts == [p.host for p in v._teste.candidatos()]
        assert "speed.cloudflare.com" in hosts
    finally:
        v._encerrar_teste()


def test_escolher_um_servidor_na_tela_fixa_ele_no_motor(tmp_path, monkeypatch):
    """A escolha manual precisa chegar ao motor E ao disco, senão ela vale até o
    app fechar, que é o mesmo que não valer."""
    _, v = _tela(tmp_path, monkeypatch)
    try:
        v.test_srv.setCurrentIndex(v.test_srv.findData("speed.cloudflare.com"))
        assert v._teste.fixado == "speed.cloudflare.com"
        assert sp.servidor_fixado() == "speed.cloudflare.com"
        v.test_srv.setCurrentIndex(0)
        assert v._teste.fixado is None
        assert sp.servidor_fixado() is None
    finally:
        v._encerrar_teste()


def test_servidor_fixado_reaparece_selecionado_na_proxima_abertura(tmp_path, monkeypatch):
    _, v = _tela(tmp_path, monkeypatch)
    v._encerrar_teste()
    sp.fixar_servidor("speedtest.gru1.linode.com")
    _, outra = _tela(tmp_path, monkeypatch)
    try:
        assert outra.test_srv.currentData() == "speedtest.gru1.linode.com"
    finally:
        outra._encerrar_teste()


def test_casa_nova_da_lista_publica_aparece_sem_reabrir_o_app(tmp_path, monkeypatch):
    """A busca da lista roda em segundo plano e só termina depois que o teste já
    começou, o que ela traz nunca está na tela no instante em que chega."""
    _, v = _tela(tmp_path, monkeypatch)
    try:
        antes = v.test_srv.count()
        sp.gravar_estado({"lista": [{"name": "Vizinha", "server": "https://vizinha/",
                                     "dlURL": "garbage.php"}],
                          "lista_quando": time.time()})
        v._atualizar_teste()
        assert v.test_srv.count() == antes + 1
        assert v.test_srv.itemData(v.test_srv.count() - 1) == "vizinha"
    finally:
        v._encerrar_teste()


def test_linha_do_servidor_diz_onde_ele_fica_e_a_que_distancia(tmp_path, monkeypatch):
    rede, _ = _tela(tmp_path, monkeypatch)
    texto = rede._texto_servidor({"servidor": "gru1.linode.com",
                                  "servidor_nome": "Linode São Paulo",
                                  "servidor_ms": 15.8, "fixado": None})
    assert "Linode São Paulo" in texto and "gru1.linode.com" in texto
    assert "15.8 ms" in texto
    assert "fixado" not in texto
    fixo = rede._texto_servidor({"servidor": "x", "servidor_nome": "x",
                                 "servidor_ms": None, "fixado": "x"})
    assert fixo == "x · fixado"
    assert rede._texto_servidor({}) == units.DASH


def test_a_tela_mostra_o_menor_teto_e_de_quem_ele_e(tmp_path, monkeypatch):
    """A resposta para "isso é a minha internet ou é o app?" precisa dizer QUAL
    limite é, e não só um número solto."""
    rede, _ = _tela(tmp_path, monkeypatch)
    assert "janela de envio" in rede._texto_teto({"teto_janela": 131.0,
                                                  "teto_processo": 13559.0})
    assert "este app" in rede._texto_teto({"teto_janela": 8949.0,
                                           "teto_processo": 2008.0})
    assert rede._texto_teto({}) == units.DASH
    assert rede._taxa(13559.0) == "13,6 Gbps"


def test_linhas_sem_conteudo_ficam_escondidas(tmp_path, monkeypatch):
    """Travessão fixo numa linha diz "isto quebrou"; linha ausente diz "ainda não
    houve medição", que é a verdade antes do primeiro teste."""
    _, v = _tela(tmp_path, monkeypatch)
    try:
        assert not v.test_rows.row("teto").isVisibleTo(v)
        assert not v.test_rows.row("envio").isVisibleTo(v)
        v._teste._publicar(servidor="dl.exemplo", servidor_envio="ul.exemplo",
                           teto_janela=131.0)
        v._atualizar_teste()
        assert v.test_rows.row("envio").isVisibleTo(v)
        assert v.test_rows.row("teto").isVisibleTo(v)
        v._teste._publicar(servidor_envio="dl.exemplo")
        v._atualizar_teste()
        assert not v.test_rows.row("envio").isVisibleTo(v), \
            "repetiu o mesmo host em duas linhas"
    finally:
        v._encerrar_teste()


def test_lista_de_servidores_trava_durante_a_medicao(tmp_path, monkeypatch):
    """Trocar de servidor no meio não teria efeito nenhum sobre a medição em
    curso; deixar clicável seria um botão que não faz o que parece."""
    _, v = _tela(tmp_path, monkeypatch)
    try:
        v._teste._publicar(rodando=True, fase=sp.FASE_DOWNLOAD)
        v._atualizar_teste()
        assert not v.test_srv.isEnabled()
        v._teste._publicar(rodando=False, fase=sp.FASE_PRONTO)
        v._atualizar_teste()
        assert v.test_srv.isEnabled()
    finally:
        v._encerrar_teste()
