"""Reimpor o arranjo padrao quando um monitor entra ou sai.

O Windows guarda a ultima topologia usada com cada conjunto de monitores. Como
a ultima vez que a TV esteve junto foi num perfil que apaga os monitores de
mesa, plugar a TV apagava os dois sozinho.
"""
import vantage.app as appmod
from vantage.app import App


class _Tela:
    def __init__(self, monitor_id, ativa=True, primaria=False):
        self.monitor_id = monitor_id
        self.name = monitor_id
        self.device = "dev:" + monitor_id
        self.active = ativa
        self.primary = primaria


class _Displays:
    def __init__(self, telas):
        self.telas = telas
        self.aplicados: list = []

    def list_displays(self, with_modes=False):
        return list(self.telas)

    def snapshot(self):
        return [{"monitor_id": t.monitor_id, "active": t.active, "primary": t.primary,
                 "position": [0, 0], "mode": None} for t in self.telas]

    def apply_profile(self, entries, topology=""):
        self.aplicados.append(entries)
        return True, ""


def _app(monkeypatch, telas, padrao=None):
    fake = _Displays(telas)
    monkeypatch.setattr(appmod, "dsp", fake)
    a = App.__new__(App)
    a._displays_seen = None
    a._displays_pending = None
    a._session = None
    a.notify = lambda *args: None
    a._normal_layout = lambda: padrao
    a._normal_topology = lambda: ""
    a.settings = type("S", (), {"display_primary_default": "", "display_off_by_default": [],
                             "display_force_native": False})()
    a.window = type("W", (), {"reload_displays": lambda self: None})()
    return a, fake


_PADRAO = [{"monitor_id": "uw", "active": True, "primary": True,
            "position": [0, 0], "mode": None},
           {"monitor_id": "tv", "active": False, "primary": False,
            "position": [0, 0], "mode": None}]


def _mudou(a, telas, novas):
    """Duas passadas: o vigia so' age com o conjunto ja' acomodado."""
    a._watch_displays()
    telas[:] = novas
    a._watch_displays()
    a._watch_displays()


def test_primeira_passada_so_memoriza():
    """Agir na abertura mexeria nas telas sem o usuario ter pedido."""
    import pytest
    mp = pytest.MonkeyPatch()
    try:
        a, fake = _app(mp, [_Tela("uw", True, True)], _PADRAO)
        a._watch_displays()
        assert fake.aplicados == []
        assert a._displays_seen == frozenset({"uw"})
    finally:
        mp.undo()


def test_nunca_reaplica_perfil(monkeypatch):
    """Perfil mexe em topologia, modos e posicoes.

    Reaplica-lo porque um monitor foi plugado apagava o arranjo que a pessoa
    tinha acabado de montar na mao: o relato foi "movo as telas, aplico, e
    depois de um tempo volta sozinho".
    """
    telas = [_Tela("uw", True, True)]
    a, fake = _app(monkeypatch, telas, _PADRAO)
    _mudou(a, telas, [_Tela("uw", True, True), _Tela("tv", True, False)])
    assert fake.aplicados == []


def test_conjunto_instavel_nao_dispara(monkeypatch):
    """Aplicar um arranjo faz o Windows soltar e reanexar caminhos por um
    instante; agir nesse piscar desfazia a mudanca recem-aplicada."""
    telas = [_Tela("uw", True, True)]
    a, fake = _app(monkeypatch, telas, _PADRAO)
    a._watch_displays()
    chamou = []
    a._enforce_display_defaults = lambda: chamou.append(1)

    telas.append(_Tela("tv", True, False))
    a._watch_displays()          # viu diferente: so' anota
    assert chamou == []
    telas.pop()                  # voltou ao que era antes de confirmar
    a._watch_displays()
    assert chamou == []


def test_conjunto_estavel_reimpoe_os_padroes(monkeypatch):
    telas = [_Tela("uw", True, True)]
    a, _fake = _app(monkeypatch, telas, _PADRAO)
    chamou = []
    a._enforce_display_defaults = lambda: chamou.append(1)
    _mudou(a, telas, [_Tela("uw", True, True), _Tela("tv", True, False)])
    assert chamou == [1]


def test_aba_telas_se_redesenha(monkeypatch):
    """Plugar um monitor com a aba Telas na frente nao mostrava nada."""
    telas = [_Tela("uw", True, True)]
    a, _fake = _app(monkeypatch, telas, None)
    redesenhos = []
    a.window = type("W", (), {"reload_displays": lambda self: redesenhos.append(1)})()
    a._enforce_display_defaults = lambda: None
    _mudou(a, telas, [_Tela("uw", True, True), _Tela("tv", True, False)])
    assert redesenhos == [1]


def test_nao_mexe_no_meio_de_um_jogo(monkeypatch):
    """Trocar de tela com o jogo aberto cai justamente em cima dele."""
    telas = [_Tela("uw", True, True)]
    a, _fake = _app(monkeypatch, telas, _PADRAO)
    chamou = []
    a._enforce_display_defaults = lambda: chamou.append(1)
    a._watch_displays()
    a._session = object()
    _mudou(a, telas, [_Tela("uw", True, True), _Tela("tv", True, False)])
    assert chamou == []


# ── principal padrao da casa ─────────────────────────────────────────────────
def _com_padrao(monkeypatch, telas, alvo):
    fake = _Displays(telas)
    monkeypatch.setattr(appmod, "dsp", fake)
    fake.primarias = []
    fake.set_primary = lambda device: (fake.primarias.append(device), (True, ""))[1]
    a = App.__new__(App)
    a._session = None
    a.settings = type("S", (), {"display_primary_default": alvo, "display_off_by_default": [],
                             "display_force_native": False})()
    a.notify = lambda *args: None
    return a, fake


def test_principal_padrao_e_devolvida(monkeypatch):
    """Plugar a TV entrega a primaria a ela; a barra de tarefas ia junto."""
    telas = [_Tela("uw", True, False), _Tela("tv", True, True)]
    a, fake = _com_padrao(monkeypatch, telas, "uw")
    assert a._enforce_primary() == "uw"
    assert fake.primarias == ["dev:uw"]


def test_nao_mexe_se_ja_esta_certa(monkeypatch):
    telas = [_Tela("uw", True, True), _Tela("tv", True, False)]
    a, fake = _com_padrao(monkeypatch, telas, "uw")
    assert a._enforce_primary() == ""
    assert fake.primarias == []


def test_tela_padrao_apagada_e_ignorada(monkeypatch):
    """Promover uma tela desligada deixaria a area de trabalho no escuro."""
    telas = [_Tela("uw", False, False), _Tela("tv", True, True)]
    a, fake = _com_padrao(monkeypatch, telas, "uw")
    assert a._enforce_primary() == ""
    assert fake.primarias == []


def test_jogo_aberto_manda_mais_que_o_padrao(monkeypatch):
    """Durante o jogo a primaria foi trocada de proposito, e por nos."""
    telas = [_Tela("uw", True, False), _Tela("tv", True, True)]
    a, fake = _com_padrao(monkeypatch, telas, "uw")
    a._session = object()
    assert a._enforce_primary() == ""
    assert fake.primarias == []


def test_sem_escolha_feita_nao_faz_nada(monkeypatch):
    telas = [_Tela("uw", True, False), _Tela("tv", True, True)]
    a, fake = _com_padrao(monkeypatch, telas, "")
    assert a._enforce_primary() == ""
    assert fake.primarias == []
