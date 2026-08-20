"""Reimpor o arranjo padrao quando um monitor entra ou sai.

O Windows guarda a ultima topologia usada com cada conjunto de monitores. Como
a ultima vez que a TV esteve junto foi num perfil que apaga os monitores de
mesa, plugar a TV apagava os dois sozinho.
"""
import dbxstats.app as appmod
from dbxstats.app import App


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
    a._session = None
    a.notify = lambda *args: None
    a._normal_layout = lambda: padrao
    a._normal_topology = lambda: ""
    return a, fake


_PADRAO = [{"monitor_id": "uw", "active": True, "primary": True,
            "position": [0, 0], "mode": None},
           {"monitor_id": "tv", "active": False, "primary": False,
            "position": [0, 0], "mode": None}]


def test_primeira_passada_so_memoriza():
    """Reimpor logo na abertura mexeria nas telas sem o usuario ter pedido."""
    import pytest
    mp = pytest.MonkeyPatch()
    try:
        a, fake = _app(mp, [_Tela("uw", True, True)], _PADRAO)
        a._watch_displays()
        assert fake.aplicados == []
        assert a._displays_seen == frozenset({"uw"})
    finally:
        mp.undo()


def test_monitor_novo_reimpoe_o_padrao(monkeypatch):
    telas = [_Tela("uw", True, True)]
    a, fake = _app(monkeypatch, telas, _PADRAO)
    a._watch_displays()

    telas.append(_Tela("tv", True, False))   # TV plugada, e o Windows a acendeu
    a._watch_displays()

    assert fake.aplicados == [_PADRAO]


def test_sem_perfil_padrao_nao_inventa_arranjo(monkeypatch):
    telas = [_Tela("uw", True, True)]
    a, fake = _app(monkeypatch, telas, None)
    a._watch_displays()
    telas.append(_Tela("tv"))
    a._watch_displays()
    assert fake.aplicados == []


def test_nao_mexe_no_meio_de_um_jogo(monkeypatch):
    """Trocar de tela com o jogo aberto cai justamente em cima dele."""
    telas = [_Tela("uw", True, True)]
    a, fake = _app(monkeypatch, telas, _PADRAO)
    a._watch_displays()
    a._session = object()
    telas.append(_Tela("tv"))
    a._watch_displays()
    assert fake.aplicados == []


def test_ligar_ou_promover_tela_nao_conta_como_mudanca(monkeypatch):
    """E' o que o proprio app faz; reagir viraria queda de braco."""
    telas = [_Tela("uw", True, True), _Tela("tv", False, False)]
    a, fake = _app(monkeypatch, telas, _PADRAO)
    a._watch_displays()

    telas[1].active = True
    telas[1].primary = True
    telas[0].primary = False
    a._watch_displays()

    assert fake.aplicados == []


def test_monitor_desconectado_tambem_reimpoe(monkeypatch):
    telas = [_Tela("uw", True, True), _Tela("tv", True, False)]
    a, fake = _app(monkeypatch, telas, _PADRAO)
    a._watch_displays()
    telas.pop()
    a._watch_displays()
    assert fake.aplicados == [_PADRAO]
