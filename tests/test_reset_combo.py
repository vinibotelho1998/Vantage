"""LT+RT+L3+R3 duas vezes: o caminho de volta ao arranjo padrao, do sofa."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("VANTAGE_NO_FILE_LOG", "1")

from vantage.platform import gamepad as G  # noqa: E402


class _Pad:
    """Estado cru do controle, so' o que o combo olha."""

    def __init__(self, lt=0, rt=0, buttons=0):
        self.bLeftTrigger = lt
        self.bRightTrigger = rt
        self.wButtons = buttons


def _mouse(monkeypatch, agora=1000.0):
    m = G.GamepadMouse.__new__(G.GamepadMouse)
    m._reset_segurado = False
    m._reset_armado_em = 0.0
    m._held = {}
    m._bindings = {}
    m.slots = []
    m.pedidos = 0
    m.reset_pedido = type("S", (), {"emit": lambda self: None})()
    monkeypatch.setattr(G.time, "monotonic", lambda: agora)
    return m


_CHEIO = G.BTN_LTHUMB | G.BTN_RTHUMB
_FORTE = G.TRIGGER_THRESHOLD + 50


def _apertar(m, monkeypatch, quando):
    monkeypatch.setattr(G.time, "monotonic", lambda: quando)
    return m._reset(_Pad(_FORTE, _FORTE, _CHEIO), _CHEIO)


def _soltar(m):
    return m._reset(_Pad(0, 0, 0), 0)


def test_uma_apertada_so_arma_e_nao_dispara(monkeypatch):
    """O gesto desfaz o arranjo inteiro da casa; uma apertada viraria acidente."""
    disparos = []
    m = _mouse(monkeypatch)
    m.reset_pedido = type("S", (), {"emit": lambda self: disparos.append(1)})()

    _apertar(m, monkeypatch, 1000.0)
    _soltar(m)

    assert disparos == []
    assert m._reset_armado_em == 1000.0


def test_duas_apertadas_dentro_da_janela_disparam(monkeypatch):
    disparos = []
    m = _mouse(monkeypatch)
    m.reset_pedido = type("S", (), {"emit": lambda self: disparos.append(1)})()

    _apertar(m, monkeypatch, 1000.0)
    _soltar(m)
    _apertar(m, monkeypatch, 1000.0 + G.RESET_JANELA_S - 0.2)

    assert disparos == [1]
    assert m._reset_armado_em == 0.0        # desarma para nao disparar em cascata


def test_segunda_apertada_tarde_demais_so_rearma(monkeypatch):
    disparos = []
    m = _mouse(monkeypatch)
    m.reset_pedido = type("S", (), {"emit": lambda self: disparos.append(1)})()

    _apertar(m, monkeypatch, 1000.0)
    _soltar(m)
    _apertar(m, monkeypatch, 1000.0 + G.RESET_JANELA_S + 1)

    assert disparos == []


def test_segurar_nao_conta_como_duas(monkeypatch):
    """Sem a borda, o laco a 125 Hz dispararia dezenas de vezes por segundo."""
    disparos = []
    m = _mouse(monkeypatch)
    m.reset_pedido = type("S", (), {"emit": lambda self: disparos.append(1)})()

    for _ in range(50):
        _apertar(m, monkeypatch, 1000.0)

    assert disparos == []


def test_combo_incompleto_nao_arma(monkeypatch):
    """Faltando um dos quatro nao e' o gesto: LT+RT sozinho ja' e' outra acao."""
    m = _mouse(monkeypatch)
    assert m._reset(_Pad(_FORTE, _FORTE, G.BTN_LTHUMB), G.BTN_LTHUMB) is False
    assert m._reset(_Pad(_FORTE, 0, _CHEIO), _CHEIO) is False
    assert m._reset(_Pad(0, 0, _CHEIO), _CHEIO) is False
    assert m._reset_armado_em == 0.0


def test_gatilho_de_leve_nao_conta(monkeypatch):
    """Gatilho e' analogico; rocar nele nao pode valer como apertado."""
    m = _mouse(monkeypatch)
    fraco = G.TRIGGER_THRESHOLD - 1
    assert m._reset(_Pad(fraco, fraco, _CHEIO), _CHEIO) is False


def test_combo_engole_a_acao_dos_botoes_que_usa(monkeypatch):
    """LT+RT ja' e' "area de trabalho", L3 e' teclado virtual e R3 e' clique do
    meio. Sem a parada, pedir o reset piscaria a area de trabalho junto."""
    m = _mouse(monkeypatch)
    assert _apertar(m, monkeypatch, 1000.0) is True     # True = o laco para aqui


def test_soltar_libera_o_laco(monkeypatch):
    m = _mouse(monkeypatch)
    _apertar(m, monkeypatch, 1000.0)
    assert _soltar(m) is False


def test_teclas_presas_sao_soltas_ao_fechar_o_combo(monkeypatch):
    """O combo passa por LT e por L3 no caminho; o que ficou pressionado
    naquele instante nao pode ficar presa no Windows."""
    soltou = []
    m = _mouse(monkeypatch)
    m._release_all = lambda: soltou.append(1)

    _apertar(m, monkeypatch, 1000.0)

    assert soltou == [1]
