"""Estimativa passiva de latencia a partir do vaivem dos pacotes."""
import random

from vantage.sensors.peer import estimate_rtt


def _conversa(rtt_ms: float, tick_ms: float, n: int, jitter_ms: float = 0.0,
              semente: int = 7) -> list[tuple[float, bool]]:
    """Cliente manda a cada tick; servidor responde um RTT depois."""
    rng = random.Random(semente)
    eventos: list[tuple[float, bool]] = []
    t = 0.0
    for _ in range(n):
        eventos.append((t, True))
        atraso = (rtt_ms + rng.uniform(0, jitter_ms)) / 1000.0
        eventos.append((t + atraso, False))
        t += tick_ms / 1000.0
    return eventos


def test_sem_pacote_suficiente_nao_inventa_numero():
    assert estimate_rtt([]) == (None, None)
    assert estimate_rtt(_conversa(20, 30, 2)) == (None, None)


def test_recupera_o_rtt_de_uma_conversa_limpa():
    rtt, jitter = estimate_rtt(_conversa(rtt_ms=16.0, tick_ms=33.0, n=60))
    assert 15.0 <= rtt <= 17.0
    assert jitter is not None and jitter < 1.0


def test_recupera_o_rtt_mesmo_com_variacao():
    rtt, jitter = estimate_rtt(_conversa(rtt_ms=40.0, tick_ms=33.0, n=120, jitter_ms=20.0))
    assert 39.0 <= rtt <= 48.0        # percentil baixo fica perto do piso real
    assert jitter > 2.0               # e a variacao aparece


def test_pacote_do_servidor_sozinho_nao_vira_medida():
    """Estado que o servidor manda por conta propria nao e' resposta a nada."""
    eventos = [(0.0, False), (0.1, False), (0.2, False)]
    assert estimate_rtt(eventos) == (None, None)


def test_intervalo_absurdo_e_descartado():
    """Servidor mudo por 3 s: isso e' o proximo ciclo, nao ida e volta."""
    eventos: list[tuple[float, bool]] = []
    for i in range(20):
        eventos.append((i * 5.0, True))
        eventos.append((i * 5.0 + 3.0, False))    # 3000 ms
    assert estimate_rtt(eventos) == (None, None)


def test_rajada_de_envios_casa_com_a_primeira_resposta():
    """Varios envios seguidos antes da resposta contam a partir do primeiro."""
    eventos = []
    for i in range(30):
        base = i * 0.05
        eventos += [(base, True), (base + 0.001, True), (base + 0.021, False)]
    rtt, _ = estimate_rtt(eventos)
    assert 20.0 <= rtt <= 22.0


def test_ordem_do_jitter_respeita_o_tempo():
    """Jitter e' variacao entre medidas seguidas, nao entre valores ordenados."""
    eventos = []
    for i, atraso in enumerate([0.020, 0.020, 0.020, 0.080, 0.020, 0.020,
                                0.020, 0.020, 0.020, 0.020]):
        base = i * 0.2
        eventos += [(base, True), (base + atraso, False)]
    _, jitter = estimate_rtt(eventos)
    assert jitter > 10.0
