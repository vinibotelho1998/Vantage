"""Conta e maquina de estados do teste de velocidade.

Nenhum teste aqui toca a internet: o transporte e' um duble. O que esta' sendo
protegido e' a honestidade do numero — nao subestimar link rapido por causa do
slow start, nao somar errado os fluxos paralelos e, acima de tudo, nunca mostrar
zero Mbps quando na verdade a rede caiu.
"""
import threading
import time

import pytest

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
    menos de 1 ms — e o usuario iria caçar problema onde nao havia.
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
    import urllib.error
    erro = urllib.error.HTTPError("http://x", 403, "Forbidden", {}, None)
    assert "403" in sp.mensagem_de_erro(erro)


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


def _motor(rede, **kw):
    """Motor com a mesma logica, so' que em escala de teste (frações de segundo)."""
    padrao = dict(fluxos=2, duracao=0.4, aquecimento=0.1, janela_minima=0.05,
                  sondas=2, timeout=1.0)
    padrao.update(kw)
    return sp.TesteDeVelocidade(rede=rede, **padrao)


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
    assert motor.aguardar(15.0)
    s = motor.snapshot()
    assert s["fase"] == sp.FASE_ERRO
    assert s["download"] is None and s["upload"] is None
    assert s["ping"] is None
    assert "sem conexão" in s["erro"]


def test_servidor_principal_fora_cai_no_reserva():
    """Plano B existe para o dia em que a Cloudflare esta' bloqueada na rede."""
    class SoOReserva(RedeFalsa):
        def baixar(self, url, cancelado, contar, timeout):
            self.urls_baixadas.append(url)
            if "principal" in url:
                raise OSError("recusado")
            while not cancelado():
                contar(self.por_chamada)
                time.sleep(0.01)

    motor = _motor(SoOReserva(), urls_download=("https://principal/x",
                                                "https://reserva/y"))
    motor.start()
    assert motor.aguardar(15.0)
    s = motor.snapshot()
    assert s["fase"] == sp.FASE_PRONTO
    assert s["download"] > 0
    assert s["servidor"] == "reserva"
    assert "reserva" in s["aviso"]


def test_upload_falho_nao_derruba_o_resto():
    """Endpoint de envio e' o elo fraco; download e ping continuam valendo."""
    motor = _motor(RedeFalsa(falhar_upload=OSError("recusado")))
    motor.start()
    assert motor.aguardar(15.0)
    s = motor.snapshot()
    assert s["fase"] == sp.FASE_PRONTO
    assert s["download"] > 0
    assert s["upload"] is None
    assert "Upload ficou de fora" in s["aviso"]


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
