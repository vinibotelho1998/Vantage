"""DualSense lido por HID: a traducao do relatorio para o formato do XInput."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("VANTAGE_NO_FILE_LOG", "1")

from vantage.platform import gamepad as G  # noqa: E402
from vantage.platform import pads as P  # noqa: E402
from vantage.platform.dualsense import Leitor, _eixo  # noqa: E402


def _relatorio(lx=128, ly=128, rx=128, ry=128, faces=0, hat=8, ombros=0, l2=0, r2=0):
    """Monta um relatorio 0x01 como o controle manda."""
    return bytes([0x01, lx, ly, rx, ry, (faces & 0xF0) | (hat & 0x0F), ombros, 0, l2, r2])


# ── eixos: o bug que fazia o cursor pular de canto ───────────────────────────
def test_nenhum_valor_do_byte_estoura_o_c_short():
    """(valor-128)*258 dava -33024 no extremo, que NAO cabe num c_short.

    O ctypes truncava calado e o numero voltava POSITIVO: empurrar o analogico
    todo para a esquerda mandava o cursor para a direita.
    """
    for b in range(256):
        assert -32768 <= _eixo(b) <= 32767


def test_extremo_negativo_chega_ao_fundo_da_escala():
    assert _eixo(0) == -32768


def test_centro_do_analogico_e_exatamente_zero():
    """Resto no meio vira deriva, e deriva no eixo do cursor e' cursor andando
    sozinho pela tela."""
    assert _eixo(128) == 0


def test_eixo_e_monotonico():
    """Sem isto o truncamento passa despercebido: os valores continuam dentro da
    faixa, mas a ordem quebra no meio."""
    valores = [_eixo(b) for b in range(256)]
    assert valores == sorted(valores)
    assert len(set(valores)) == 256


def test_struct_guarda_o_que_foi_calculado():
    """O truncamento acontecia na ESCRITA no c_short, nao na conta."""
    for b in (0, 1, 127, 128, 255):
        pad = Leitor._decodificar(_relatorio(lx=b, ly=b))
        assert pad.sThumbLX == _eixo(b)
        assert pad.sThumbLY == -_eixo(b) - 1


def test_eixo_y_e_invertido():
    """HID cresce para baixo, XInput para cima. Sem inverter, empurrar o
    analogico para cima desceria o cursor."""
    pad = Leitor._decodificar(_relatorio(ly=0))
    assert pad.sThumbLY > 0


def test_repouso_fica_dentro_da_zona_morta_padrao():
    pad = Leitor._decodificar(_relatorio())
    assert abs(pad.sThumbLX) < 8000
    assert abs(pad.sThumbLY) < 8000


# ── botoes ───────────────────────────────────────────────────────────────────
def test_xis_vira_A_pela_posicao_no_controle():
    """O Xis da Sony fica onde fica o A do Xbox. Casar por letra colocaria
    "confirmar" no botao de cima."""
    assert Leitor._decodificar(_relatorio(faces=0x20)).wButtons == G.BTN_A


def test_quadrado_vira_X_e_triangulo_vira_Y():
    assert Leitor._decodificar(_relatorio(faces=0x10)).wButtons == G.BTN_X
    assert Leitor._decodificar(_relatorio(faces=0x80)).wButtons == G.BTN_Y


def test_create_e_options_viram_back_e_start():
    """Sao os dois do combo que assume e devolve o mouse; errar aqui deixaria o
    modo mouse sem atalho nenhum."""
    assert Leitor._decodificar(_relatorio(ombros=0x10)).wButtons == G.BTN_BACK
    assert Leitor._decodificar(_relatorio(ombros=0x20)).wButtons == G.BTN_START


def test_combo_back_mais_start_sai_junto():
    pad = Leitor._decodificar(_relatorio(ombros=0x30))
    assert pad.wButtons & G.BTN_BACK
    assert pad.wButtons & G.BTN_START


def test_gatilhos_analogicos_nao_viram_botao():
    """L2 e R2 tambem acendem bits em `ombros`; usar esses bits perderia o meio
    do curso do gatilho."""
    pad = Leitor._decodificar(_relatorio(ombros=0x0C, l2=200, r2=180))
    assert pad.bLeftTrigger == 200
    assert pad.bRightTrigger == 180
    assert pad.wButtons == 0


# ── direcional ───────────────────────────────────────────────────────────────
def test_direcional_solto_nao_acende_nada():
    assert Leitor._decodificar(_relatorio(hat=8)).wButtons == 0


def test_direcional_para_cima():
    assert Leitor._decodificar(_relatorio(hat=0)).wButtons == G.BTN_DPAD_UP


def test_diagonal_acende_os_dois_lados():
    """E' como o XInput representa diagonal, e e' o que faz `nav_direction`
    decidir igual nos dois tipos de controle."""
    pad = Leitor._decodificar(_relatorio(hat=1))
    assert pad.wButtons == (G.BTN_DPAD_UP | G.BTN_DPAD_RIGHT)


def test_direcional_e_botao_convivem():
    pad = Leitor._decodificar(_relatorio(faces=0x20, hat=4))
    assert pad.wButtons == (G.BTN_A | G.BTN_DPAD_DOWN)


# ── robustez ─────────────────────────────────────────────────────────────────
def test_relatorio_curto_e_descartado():
    """Relatorio truncado nao pode virar estado com lixo dentro."""
    assert Leitor._decodificar(b"\x01\x80\x80") is None


# ── legibilidade separada do XInput ──────────────────────────────────────────
def _pad(**kw):
    base = dict(name="x", vid=P.SONY, pid=0x0CE6, bus="Bluetooth",
                xinput=False, slot=None, path="")
    base.update(kw)
    return P.Pad(**base)


def test_dualsense_e_legivel_mesmo_sem_xinput():
    """O erro que a tela cometia: dizer "o app nao le" sobre o controle que
    estava, naquele instante, movendo o cursor."""
    pad = _pad()
    assert pad.xinput is False
    assert pad.readable is True
    assert pad.how == "HID"


def test_controle_xinput_continua_legivel():
    pad = _pad(vid=0x2DC8, pid=0x3106, xinput=True)
    assert pad.readable is True
    assert pad.how == "XInput"


def test_controle_generico_sem_xinput_nao_e_legivel():
    pad = _pad(vid=0x1234, pid=0x5678, xinput=False)
    assert pad.readable is False
    assert pad.how == ""
