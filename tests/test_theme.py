"""Faixas de cor e contas de cor do tema.

A cor e' o que o olho le' antes do numero: uma faixa com o limiar trocado pinta
de vermelho a maquina que esta' bem, ou de verde a que esta' fervendo.
"""
import pytest

from vantage import theme


@pytest.fixture(autouse=True)
def _escala_intacta():
    antes = theme.SCALE
    yield
    theme.SCALE = antes


def test_temperatura_muda_de_faixa_exatamente_nos_limiares():
    assert theme.temp_color(64.9) == theme.OK
    assert theme.temp_color(65) == theme.WARN
    assert theme.temp_color(81.9) == theme.WARN
    assert theme.temp_color(82) == theme.BAD
    assert theme.temp_color(91.9) == theme.BAD
    assert theme.temp_color(92) == theme.CRIT


def test_sem_leitura_e_cinza_e_nao_verde():
    """Sensor mudo pintado de verde diria 'tudo bem' sem ter medido nada."""
    for f in (theme.temp_color, theme.vram_temp_color, theme.load_color,
              theme.fps_color, theme.frametime_color, theme.stutter_color,
              theme.ping_color, theme.loss_color, theme.score_color,
              theme.dimm_temp_color):
        assert f(None) == theme.MUTE, f.__name__
    assert theme.watt_color(None, 100, 200) == theme.MUTE


def test_vram_tem_regua_propria():
    assert theme.vram_temp_color(85) == theme.OK
    assert theme.temp_color(85) == theme.BAD
    assert theme.vram_temp_color(95) == theme.WARN
    assert theme.vram_temp_color(105) == theme.BAD


def test_pente_de_memoria_usa_os_limites_de_fabrica_quando_existem():
    assert theme.dimm_temp_color(56) == theme.WARN
    assert theme.dimm_temp_color(56, high=70, critical=90) == theme.OK
    assert theme.dimm_temp_color(75, high=70, critical=90) == theme.WARN
    assert theme.dimm_temp_color(90, high=70, critical=90) == theme.BAD


def test_nota_mais_alta_e_melhor():
    assert theme.score_color(95) == theme.OK
    assert theme.score_color(80) == theme.OK
    assert theme.score_color(79) == theme.WARN
    assert theme.score_color(55) == theme.WARN
    assert theme.score_color(54) == theme.BAD


def test_fps_por_faixa():
    assert theme.fps_color(144) == theme.OK
    assert theme.fps_color(100) == theme.OK
    assert theme.fps_color(60) not in (theme.OK, theme.WARN, theme.BAD)
    assert theme.fps_color(30) == theme.WARN
    assert theme.fps_color(29) == theme.BAD


def test_perda_zero_e_verde_e_qualquer_perda_ja_e_aviso():
    assert theme.loss_color(0) == theme.OK
    assert theme.loss_color(0.5) == theme.WARN
    assert theme.loss_color(15) == theme.BAD


def test_rgba_converte_hex_para_qss():
    assert theme.rgba("#FF8000", 0.5) == "rgba(255, 128, 0, 0.500)"
    assert theme.rgba("22D3EE", 1) == "rgba(34, 211, 238, 1.000)"


def test_mistura_nas_pontas_e_no_meio():
    assert theme.mix("#000000", "#FFFFFF", 0) == "#000000"
    assert theme.mix("#000000", "#FFFFFF", 1) == "#FFFFFF"
    assert theme.mix("#000000", "#FFFFFF", 0.5) == "#808080"


def test_mistura_fora_de_0_a_1_nao_estoura_o_hex():
    assert theme.mix("#000000", "#FFFFFF", 7) == "#FFFFFF"
    assert theme.mix("#101010", "#FFFFFF", -3) == "#101010"


def test_destaque_desconhecido_cai_no_ciano():
    assert theme.accent_color("neon") == theme.ACCENTS["cyan"].color
    assert theme.accent_color("purple") == theme.ACCENTS["purple"].color


def test_escala_da_interface_tem_limites():
    theme.set_scale(5)
    assert theme.SCALE == 2.0
    theme.set_scale(0.1)
    assert theme.SCALE == 0.75


def test_escalado_nunca_vira_zero_pixel():
    theme.set_scale(0.75)
    assert theme.scaled(0.4) == 1
    theme.set_scale(1.5)
    assert theme.scaled(10) == 15
