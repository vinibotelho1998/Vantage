"""UDP sem sequencia ou ACK nao permite atribuir uma resposta ao envio."""
from vantage.sensors.peer import estimate_rtt


def test_fluxo_continuo_nao_publica_falso_rtt_de_um_ms():
    # Um RTT real de 81 ms e trafego a 100 Hz tem a mesma ordem temporal
    # observavel de um RTT de 1 ms. Sem IDs, a associacao e ambigua.
    eventos = sorted([(i * .01, True) for i in range(100)]
                     + [(i * .01 + .081, False) for i in range(100)])
    assert estimate_rtt(eventos) == (None, None)


def test_envio_seguido_de_recebimento_independente_nao_vira_rtt():
    eventos = []
    for i in range(60):
        eventos.extend([(i * .033, True), (i * .033 + .016, False)])
    assert estimate_rtt(eventos) == (None, None)


def test_rajadas_sem_correlacao_nao_viram_medida():
    eventos = []
    for i in range(30):
        eventos.extend([(i * .05, True), (i * .05 + .001, True), (i * .05 + .021, False)])
    assert estimate_rtt(eventos) == (None, None)


def test_sem_envio_ou_sem_eventos_nao_inventa_numero():
    assert estimate_rtt([]) == (None, None)
    assert estimate_rtt([(0.0, False), (.1, False)]) == (None, None)
