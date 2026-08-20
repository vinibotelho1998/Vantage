"""Ritmo de coleta conforme quem esta' olhando.

Ler todos os sensores custa ~17 ms. A 1 Hz isso e' quase 2% de um nucleo o
tempo todo — e com um jogo na frente esse nucleo faz falta, justamente quando
ninguem esta' vendo o painel.
"""
from dbxstats.app import BACKGROUND_INTERVAL_S, App


def _app(janela_visivel, tela_cheia, overlay_visivel, base=1.0, hz=3.0):
    a = App.__new__(App)
    a._load_now = ""
    a._fg_fullscreen = tela_cheia
    a.window = type("W", (), {"isVisible": lambda self: janela_visivel})()
    if overlay_visivel is None:
        a._overlay = None
    else:
        a._overlay = type("O", (), {"isVisible": lambda self: overlay_visivel})()
    a.settings = type("S", (), {"update_interval": base, "overlay_refresh_hz": hz})()
    a._t_sys = None
    a.aplicados = []
    a.collector = type("C", (), {"set_interval": lambda self, v: a.aplicados.append(v)})()
    return a


def test_painel_aberto_mantem_o_ritmo_cheio():
    a = _app(True, False, None)
    a._apply_load_profile()
    assert a._load_now == "painel"
    assert a.aplicados == [1.0]


def test_jogo_em_tela_cheia_segue_o_overlay():
    """Medir mais rapido do que o overlay desenha e' trabalho que ninguem ve."""
    a = _app(True, True, True, base=0.5, hz=2.0)
    a._apply_load_profile()
    assert a._load_now == "overlay"
    assert a.aplicados == [0.5]          # 1/2 Hz = 0,5 s, igual a base


def test_overlay_lento_alarga_o_passo():
    a = _app(False, True, True, base=0.5, hz=1.0)
    a._apply_load_profile()
    assert a.aplicados == [1.0]


def test_ninguem_olhando_cai_para_o_fundo():
    a = _app(False, True, None)
    a._apply_load_profile()
    assert a._load_now == "fundo"
    assert a.aplicados == [BACKGROUND_INTERVAL_S]


def test_janela_escondida_sem_overlay_tambem_e_fundo():
    a = _app(False, False, False)
    a._apply_load_profile()
    assert a._load_now == "fundo"


def test_nunca_mede_mais_rapido_que_o_pedido():
    """O intervalo escolhido pelo usuario e' piso, nunca teto."""
    a = _app(False, True, True, base=2.0, hz=10.0)
    a._apply_load_profile()
    assert a.aplicados == [2.0]


def test_nao_reaplica_sem_mudanca():
    """Trocar o intervalo do timer a cada meio segundo seria pior que o mal."""
    a = _app(True, False, None)
    a._apply_load_profile()
    a._apply_load_profile()
    a._apply_load_profile()
    assert len(a.aplicados) == 1
