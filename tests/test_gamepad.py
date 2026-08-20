"""Combo Back+Start: precisa ligar E desligar o modo mouse."""
from dbxstats.platform.gamepad import BTN_BACK, BTN_START, XINPUT_GAMEPAD, GamepadMouse
from dbxstats.platform import gamepad as G


class FakeCfg:
    gamepad_toggle_combo = True
    gamepad_speed = 1.0
    gamepad_deadzone = 8000
    gamepad_scroll_speed = 1.0


def _engine(monkeypatch):
    pad = XINPUT_GAMEPAD()
    gp = GamepadMouse(FakeCfg())
    monkeypatch.setattr(gp, "_read", lambda: pad)
    monkeypatch.setattr(gp, "_feedback", lambda value: None)
    return gp, pad


def _press(gp, pad, buttons):
    pad.wButtons = buttons
    gp._tick()


def test_combo_liga_e_desliga(monkeypatch):
    gp, pad = _engine(monkeypatch)
    combo = BTN_BACK | BTN_START

    _press(gp, pad, combo)
    assert gp.active is True

    _press(gp, pad, combo)          # segurando nao repete
    assert gp.active is True

    _press(gp, pad, 0)              # soltou
    _press(gp, pad, combo)
    assert gp.active is False       # <- so' ligava antes: _release_all limpava a borda

    _press(gp, pad, combo)
    assert gp.active is False

    _press(gp, pad, 0)
    _press(gp, pad, combo)
    assert gp.active is True


def test_combo_desligado_nas_configuracoes(monkeypatch):
    gp, pad = _engine(monkeypatch)
    gp.cfg.gamepad_toggle_combo = False
    _press(gp, pad, BTN_BACK | BTN_START)
    assert gp.active is False


def test_controle_sumindo_desliga_o_modo(monkeypatch):
    gp, pad = _engine(monkeypatch)
    _press(gp, pad, BTN_BACK | BTN_START)
    assert gp.active is True
    monkeypatch.setattr(gp, "_read", lambda: None)
    gp._tick()
    assert gp.active is False


# ── mapeamento configuravel ───────────────────────────────────────────────────
class _CfgFalso:
    def __init__(self, bindings=None):
        self.gamepad_bindings = bindings or {}


def test_padrao_cobre_todos_os_botoes_da_tela():
    """Botao listado na tela sem padrao apareceria como 'Nada' sem querer."""
    for nome in G.BUTTON_ORDER:
        assert nome in G.DEFAULT_BINDINGS


def test_toda_acao_padrao_existe_no_registro():
    for nome, acao in G.DEFAULT_BINDINGS.items():
        assert acao in G.ACTIONS, f"{nome} aponta para acao inexistente"


def test_gatilho_direito_vai_para_a_area_de_trabalho():
    assert G.DEFAULT_BINDINGS["RT"] == "desktop"


def test_a_e_bola_sao_os_cliques():
    assert G.DEFAULT_BINDINGS["A"] == "click_left"
    assert G.DEFAULT_BINDINGS["B"] == "click_right"


def test_back_fica_livre_para_o_combo():
    """Com acao no Back, chegar no combo Back+Start dispararia ela antes."""
    assert G.DEFAULT_BINDINGS["Back"] == ""


def test_troca_do_usuario_vence_o_padrao():
    mapa = G.bindings_from(_CfgFalso({"RT": "vol_up"}))
    assert mapa["RT"] == "vol_up"
    assert mapa["A"] == "click_left"


def test_configuracao_estragada_e_ignorada():
    """settings.json de outra versao nao pode deixar botao sem funcao."""
    mapa = G.bindings_from(_CfgFalso({"RT": "acao_que_nao_existe", "Botao X": "win"}))
    assert mapa["RT"] == G.DEFAULT_BINDINGS["RT"]
    assert "Botao X" not in mapa


def test_descricao_sai_do_mapeamento_em_uso():
    linhas = dict(G.describe(_CfgFalso({"RT": "vol_mute"})))
    assert linhas["RT"] == "Mudo"
