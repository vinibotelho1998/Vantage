"""Gravador da partida inteira.

Guardar frame a frame nao serve: uma sessao de tres horas a 144 fps passa de
um milhao e meio de amostras, centenas de megabytes presos justamente enquanto
o jogo precisa da memoria. O gravador troca a lista por um histograma de
tamanho fixo; e os percentis tem de continuar batendo.
"""
import random

from dbxstats.core.frames import SessionRecorder


def _grava(fts) -> SessionRecorder:
    r = SessionRecorder()
    for ft in fts:
        r.add(ft)
    return r


def _low_exato(fts, fracao=0.01) -> float:
    piores = sorted(fts, reverse=True)[:max(1, int(len(fts) * fracao))]
    return 1000.0 / (sum(piores) / len(piores))


def test_um_por_cento_low_bate_com_o_calculo_exato():
    random.seed(11)
    fts = [random.gauss(7.0, 0.7) for _ in range(200_000)] + [55.0] * 30
    r = _grava(fts)
    exato = _low_exato(fts)
    obtido = r.result()["low_1"]
    assert abs(obtido - exato) / exato < 0.02, f"{obtido} vs {exato}"


def test_memoria_nao_cresce_com_a_duracao():
    curta, longa = _grava([7.0] * 1000), _grava([7.0] * 500_000)
    assert len(curta.bins) == len(longa.bins)


def test_frame_invalido_e_descartado():
    """Zero, negativo e NaN aparecem no CSV e envenenariam a media."""
    r = _grava([7.0, 0.0, -3.0, float("nan"), 7.0])
    assert r.count == 2
    assert r.result()["fps_avg"] == 142.9


def test_sessao_vazia_nao_explode():
    assert _grava([]).result() == {"frames": 0}


def test_travadas_e_engasgos_sao_contados():
    """50 ms e' travada; frame 1,5x mais lento que o anterior e' engasgo."""
    r = _grava([7.0] * 50 + [60.0] + [7.0] * 50)
    res = r.result()
    assert res["hitches"] == 1
    assert res["stutters"] >= 1


def test_frame_absurdo_vai_para_o_estouro_sem_perder_o_pior():
    """Acima do teto do histograma ainda precisa aparecer como pior frame."""
    r = _grava([7.0] * 1000 + [900.0])
    res = r.result()
    assert r.over == 1
    assert res["ft_max"] == 900.0
    assert res["fps_min"] == round(1000.0 / 900.0, 1)


def test_vsync_travado_da_media_exata():
    r = _grava([1000.0 / 144.0] * 10_000)
    assert abs(r.result()["fps_avg"] - 144.0) < 0.2


def test_custo_por_frame_e_constante():
    """Se o gravador ficar caro, ele vira o proprio problema que evita."""
    import time
    r = SessionRecorder()
    inicio = time.perf_counter()
    for _ in range(200_000):
        r.add(7.0)
    gasto = time.perf_counter() - inicio
    # 200 mil frames sao ~23 min a 144 fps; tem de sair em fracao de segundo.
    assert gasto < 1.0, f"{gasto:.2f}s para 200k frames"
