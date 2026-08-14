"""Combo Back+Start: precisa ligar E desligar o modo mouse."""
from dbxstats.platform.gamepad import BTN_BACK, BTN_START, XINPUT_GAMEPAD, GamepadMouse


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
