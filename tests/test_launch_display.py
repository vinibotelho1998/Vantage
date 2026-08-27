"""Atalho de jogo que acorda a TV.

O arranjo da casa e' a TV desligada. O atalho tem de liga-la, coloca-la na
frente, abrir o jogo, e desfazer os dois quando o jogo fechar, sem reaplicar
perfil nenhum (era o que apagava as tres telas por varios segundos).
"""
import dbxstats.app as appmod
from dbxstats.app import App


class _Tela:
    def __init__(self, monitor_id, nome, ativa, primaria):
        self.monitor_id = monitor_id
        self.name = nome
        self.device = "dev:" + monitor_id
        self.active = ativa
        self.primary = primaria


class _Displays:
    """Dublê do modulo de telas, guardando a ordem das chamadas."""

    def __init__(self, telas):
        self.telas = telas
        self.chamadas: list[tuple] = []

    def list_displays(self, with_modes=False):
        return list(self.telas)

    def _por_device(self, device):
        return next(t for t in self.telas if t.device == device)

    def set_enabled(self, device, ligada):
        self.chamadas.append(("enabled", device, ligada))
        self._por_device(device).active = ligada
        return True, ""

    def set_primary(self, device):
        self.chamadas.append(("primary", device))
        for t in self.telas:
            t.primary = t.device == device
        return True, ""

    def apply_profile(self, *a, **k):
        self.chamadas.append(("profile",))
        return True, ""


def _app(monkeypatch, telas):
    fake = _Displays(telas)
    monkeypatch.setattr(appmod, "dsp", fake)
    a = App.__new__(App)
    a._session_off = ""
    a._session_name = "jogo"
    a.settings = type("S", (), {"display_profiles": []})()
    a.notify = lambda *args: None
    return a, fake


def test_tela_desligada_acende_e_assume(monkeypatch):
    telas = [_Tela("uw", "ULTRAWIDE", True, True), _Tela("tv", "Beyond TV", False, False)]
    a, fake = _app(monkeypatch, telas)

    trocou, msg = a._apply_target("primary:tv")

    assert trocou
    assert fake.chamadas == [("enabled", "dev:tv", True), ("primary", "dev:tv")]
    assert a._session_off == "tv"
    assert "ligada" in msg


def test_tela_ja_ligada_so_vira_principal(monkeypatch):
    """Sem ligar nada, nada a desligar depois."""
    telas = [_Tela("uw", "ULTRAWIDE", True, True), _Tela("tv", "Beyond TV", True, False)]
    a, fake = _app(monkeypatch, telas)

    a._apply_target("primary:tv")

    assert fake.chamadas == [("primary", "dev:tv")]
    assert a._session_off == ""


def test_volta_devolve_a_principal_antes_de_apagar_a_tv(monkeypatch):
    """O Windows nao desliga a tela que esta' mandando: a ordem e' obrigatoria."""
    telas = [_Tela("uw", "ULTRAWIDE", True, False), _Tela("tv", "Beyond TV", True, True)]
    a, fake = _app(monkeypatch, telas)

    a._restore_primary("uw", "tv")

    assert fake.chamadas == [("primary", "dev:uw"), ("enabled", "dev:tv", False)]
    assert ("profile",) not in fake.chamadas


def test_falha_ao_assumir_desfaz_o_que_ligamos(monkeypatch):
    """Acender a TV e parar no meio deixaria uma tela extra sem motivo."""
    telas = [_Tela("uw", "ULTRAWIDE", True, True), _Tela("tv", "Beyond TV", False, False)]
    a, fake = _app(monkeypatch, telas)
    fake.set_primary = lambda device: (False, "recusado")

    trocou, _msg = a._apply_target("primary:tv")

    assert not trocou
    assert a._session_off == ""
    assert ("enabled", "dev:tv", False) in fake.chamadas


def test_tela_ausente_nao_cancela_o_jogo(monkeypatch):
    """Quem clicou em Jogar quer jogar; tela sumida vira aviso, nao bloqueio."""
    a, fake = _app(monkeypatch, [_Tela("uw", "ULTRAWIDE", True, True)])
    trocou, msg = a._apply_target("primary:tv")
    assert not trocou
    assert "não está conectada" in msg
    assert fake.chamadas == []
