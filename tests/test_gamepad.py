"""Combo Back+Start: precisa ligar E desligar o modo mouse."""
from vantage.platform.gamepad import BTN_BACK, BTN_START, XINPUT_GAMEPAD, GamepadMouse
from vantage.platform import gamepad as G


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


def test_area_de_trabalho_exige_os_dois_gatilhos():
    """Win+D e um INTERRUPTOR: a segunda apertada traz as janelas de volta.

    Num gatilho sozinho, que e analogico e dispara com um rocar, isso virava "o
    jogo volta sozinho toda hora": foi o relato de uso.
    """
    assert G.DEFAULT_BINDINGS["LT+RT"] == "desktop"
    assert G.DEFAULT_BINDINGS["RT"] == ""
    assert G.DEFAULT_BINDINGS["LT"] == ""


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


def test_par_de_gatilhos_cala_os_individuais():
    """Sem isso, apertar os dois dispararia tres acoes de uma vez, e a acao de
    cada gatilho ficaria presa quando o par se desfizesse."""
    cfg = _CfgFalso({"LT": "key_esc", "RT": "key_enter", "LT+RT": "desktop"})
    eng = G.GamepadMouse.__new__(G.GamepadMouse)
    eng.cfg = cfg
    eng._held = {}
    eng._bindings = G.bindings_from(cfg)
    disparos = []
    eng._apply = lambda nome, pressed: disparos.append((nome, pressed))

    pad = G.XINPUT_GAMEPAD()
    pad.bLeftTrigger = 200
    pad.bRightTrigger = 200
    eng._triggers(pad)
    assert ("LT+RT", True) in disparos
    assert ("LT", False) in disparos and ("RT", False) in disparos


def test_gatilho_sozinho_continua_valendo():
    cfg = _CfgFalso({"LT": "key_esc"})
    eng = G.GamepadMouse.__new__(G.GamepadMouse)
    eng.cfg = cfg
    eng._held = {}
    eng._bindings = G.bindings_from(cfg)
    disparos = []
    eng._apply = lambda nome, pressed: disparos.append((nome, pressed))

    pad = G.XINPUT_GAMEPAD()
    pad.bLeftTrigger = 200
    eng._triggers(pad)
    assert ("LT", True) in disparos
    assert ("LT+RT", False) in disparos


# ── silhueta conforme o controle conectado ───────────────────────────────────
def test_diagrama_usa_layout_sony_quando_pedido():
    """DualSense tem o direcional em cima e os dois analogicos embaixo. Desenhar
    sempre o Xbox obriga o dono a traduzir a posicao de cada botao de cabeca."""
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from vantage.ui.views.gamepad import ControllerDiagram

    QApplication.instance() or QApplication([])
    d = ControllerDiagram()
    assert d.kind == "xbox"
    xbox = dict((k, (x, y)) for k, x, y, _r, _w in d.controles)

    d.set_kind("sony")
    sony = dict((k, (x, y)) for k, x, y, _r, _w in d.controles)

    # o que muda de lugar e' exatamente o par direcional/analogico esquerdo
    assert sony["dpad"][1] < sony["lstick"][1]
    assert xbox["lstick"][1] < xbox["dpad"][1]


def test_todo_botao_desenhado_tem_geometria():
    """`_GEOM` alimenta os rotulos; uma peca fora dele quebraria o desenho."""
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from vantage.ui.views.gamepad import ControllerDiagram

    QApplication.instance() or QApplication([])
    d = ControllerDiagram()
    for kind in ("xbox", "sony"):
        d.set_kind(kind)
        chaves = {k for k, *_ in d.controles}
        assert set(d._GEOM) == chaves
        assert chaves == {"lt", "lb", "lstick", "dpad", "back", "start",
                          "y", "x", "b", "a", "rb", "rt", "rstick"}


# ── botao preso: a causa do foco andando sozinho ─────────────────────────────
def _mouse_mode():
    """GamepadMouse sem Qt: so' o que `stuck` precisa."""
    from vantage.platform.gamepad import GamepadMouse

    m = GamepadMouse.__new__(GamepadMouse)
    m._preso_desde = {}
    return m


def test_botao_recem_apertado_nao_e_preso(monkeypatch):
    """Apertar um botao nao pode virar acusacao imediata."""
    from vantage.platform import gamepad as G

    m = _mouse_mode()
    monkeypatch.setattr(G.time, "monotonic", lambda: 1000.0)
    m._vigiar_presos(G.BTN_DPAD_RIGHT)
    assert m.stuck() == []


def test_botao_apertado_alem_do_limiar_e_denunciado(monkeypatch):
    """O caso real: o direcional vai para as setas do teclado, e as setas mexem
    o foco de QUALQUER aplicativo do Windows."""
    from vantage.platform import gamepad as G

    m = _mouse_mode()
    monkeypatch.setattr(G.time, "monotonic", lambda: 1000.0)
    m._vigiar_presos(G.BTN_DPAD_RIGHT)

    monkeypatch.setattr(G.time, "monotonic", lambda: 1000.0 + G.STUCK_S + 1)
    presos = m.stuck()
    assert [nome for nome, _ in presos] == ["Direcional →"]
    assert presos[0][1] > G.STUCK_S


def test_soltar_o_botao_limpa_a_acusacao(monkeypatch):
    from vantage.platform import gamepad as G

    m = _mouse_mode()
    monkeypatch.setattr(G.time, "monotonic", lambda: 1000.0)
    m._vigiar_presos(G.BTN_A)
    monkeypatch.setattr(G.time, "monotonic", lambda: 1100.0)
    assert m.stuck()

    m._vigiar_presos(0)
    assert m.stuck() == []


def test_varios_presos_saem_do_mais_antigo(monkeypatch):
    from vantage.platform import gamepad as G

    m = _mouse_mode()
    monkeypatch.setattr(G.time, "monotonic", lambda: 1000.0)
    m._vigiar_presos(G.BTN_DPAD_UP)
    monkeypatch.setattr(G.time, "monotonic", lambda: 1010.0)
    m._vigiar_presos(G.BTN_DPAD_UP | G.BTN_B)
    monkeypatch.setattr(G.time, "monotonic", lambda: 1100.0)

    presos = m.stuck()
    assert [nome for nome, _ in presos] == ["Direcional ↑", "B"]


def test_apertar_de_novo_reinicia_a_contagem(monkeypatch):
    """Soltar e apertar e' uso normal; a contagem nao pode acumular entre os dois."""
    from vantage.platform import gamepad as G

    m = _mouse_mode()
    monkeypatch.setattr(G.time, "monotonic", lambda: 1000.0)
    m._vigiar_presos(G.BTN_A)
    monkeypatch.setattr(G.time, "monotonic", lambda: 1100.0)
    m._vigiar_presos(0)
    m._vigiar_presos(G.BTN_A)
    assert m.stuck() == []


def test_teclado_virtual_nao_pisca_console_na_tela(monkeypatch):
    """O app e' janela, sem console: tasklist e taskkill chamados sem
    CREATE_NO_WINDOW abriam uma janela preta a cada toque em L3, bem na TV."""
    import subprocess

    chamadas = []

    def _run(cmd, **kw):
        chamadas.append((cmd[0], kw))
        # tasklist responde que o teclado esta' aberto: o proximo passo fecha.
        return subprocess.CompletedProcess(cmd, 0, "osk.exe  1234 Console", "")

    monkeypatch.setattr(subprocess, "run", _run)
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: None)

    G.toggle_osk()

    assert [nome for nome, _ in chamadas] == ["tasklist", "taskkill"]
    for nome, kw in chamadas:
        assert kw.get("creationflags", 0) & subprocess.CREATE_NO_WINDOW, nome
