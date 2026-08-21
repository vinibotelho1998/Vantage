"""Arranjo padrao: acende, entrega a primaria, apaga e devolve o modo nativo.

O PC vinha ligando "com resolucao doida": o Windows chuta um modo conservador ao
reanexar tela, e o app so' sabia apagar e trocar a primaria — nunca acender o que
deveria estar aceso, nem corrigir o modo.
"""
import dbxstats.app as appmod
from dbxstats.app import App


class _Modo:
    def __init__(self, w, h, hz):
        self.width, self.height, self.refresh = w, h, hz
        self.label = f"{w} x {h} @ {hz} Hz"

    def as_key(self):
        return (self.width, self.height, self.refresh)


class _Tela:
    def __init__(self, mid, nome, ativa, primaria=False, modo=None):
        self.monitor_id, self.name = mid, nome
        self.device = "dev:" + mid
        self.active, self.primary = ativa, primaria
        self.mode = modo


class _Displays:
    def __init__(self, telas, nativo=None):
        self.telas = telas
        self.passos: list = []
        self._nativo = nativo or {}

    def list_displays(self, with_modes=True):
        return list(self.telas)

    def _por(self, device):
        return next(t for t in self.telas if t.device == device)

    def set_enabled(self, device, ligada):
        self.passos.append(("enabled", device, ligada))
        self._por(device).active = ligada
        return True, ""

    def set_primary(self, device):
        self.passos.append(("primary", device))
        for t in self.telas:
            t.primary = t.device == device
        return True, ""

    def best_mode(self, device):
        return self._nativo.get(device)

    def set_mode(self, device, modo):
        self.passos.append(("mode", device, modo.as_key()))
        self._por(device).mode = modo
        return True, ""


def _app(monkeypatch, telas, principal="", apagar=(), nativo=None, forcar=True):
    fake = _Displays(telas, nativo)
    monkeypatch.setattr(appmod, "dsp", fake)
    a = App.__new__(App)
    a._session = None
    a.notify = lambda *args: None
    a.settings = type("S", (), {
        "display_primary_default": principal,
        "display_off_by_default": list(apagar),
        "display_force_native": forcar,
    })()
    return a, fake


def test_acende_antes_de_promover_e_apaga_depois(monkeypatch):
    """A ordem nao e' negociavel: o Windows nao promove tela apagada, nem
    desliga a que esta' mandando."""
    telas = [_Tela("uw", "ULTRAWIDE", False, modo=_Modo(3440, 1440, 160)),
             _Tela("tv", "TV", True, True, modo=_Modo(3840, 2160, 120))]
    a, fake = _app(monkeypatch, telas, principal="uw", apagar=["tv"], forcar=False)
    a._enforce_display_defaults()
    assert fake.passos == [("enabled", "dev:uw", True),
                           ("primary", "dev:uw"),
                           ("enabled", "dev:tv", False)]


def test_devolve_o_modo_nativo(monkeypatch):
    """120 Hz num painel de 144, ou 4096 numa TV 4K: e' o chute do Windows."""
    tv = _Tela("tv", "TV", True, True, modo=_Modo(3840, 2160, 120))
    nativo = {"dev:tv": _Modo(3840, 2160, 144)}
    a, fake = _app(monkeypatch, [tv], nativo=nativo)
    a._enforce_display_defaults()
    assert ("mode", "dev:tv", (3840, 2160, 144)) in fake.passos


def test_modo_ja_certo_nao_e_reaplicado(monkeypatch):
    tv = _Tela("tv", "TV", True, True, modo=_Modo(3840, 2160, 144))
    nativo = {"dev:tv": _Modo(3840, 2160, 144)}
    a, fake = _app(monkeypatch, [tv], nativo=nativo)
    a._enforce_display_defaults()
    assert not [p for p in fake.passos if p[0] == "mode"]


def test_opcao_desligada_nao_mexe_no_modo(monkeypatch):
    """Quem usa modo nao nativo de proposito nao pode ser corrigido a forca."""
    tv = _Tela("tv", "TV", True, True, modo=_Modo(1920, 1080, 60))
    nativo = {"dev:tv": _Modo(3840, 2160, 144)}
    a, fake = _app(monkeypatch, [tv], nativo=nativo, forcar=False)
    a._enforce_display_defaults()
    assert not [p for p in fake.passos if p[0] == "mode"]


def test_com_jogo_aberto_nao_mexe_no_arranjo(monkeypatch):
    """As telas foram trocadas de proposito, e por nos."""
    telas = [_Tela("uw", "ULTRAWIDE", False, modo=_Modo(3440, 1440, 160)),
             _Tela("tv", "TV", True, True, modo=_Modo(3840, 2160, 144))]
    a, fake = _app(monkeypatch, telas, principal="uw", apagar=["tv"])
    a._session = object()
    a._enforce_display_defaults()
    assert not [p for p in fake.passos if p[0] == "enabled"]


def test_tela_sem_marcacao_nao_e_apagada(monkeypatch):
    """So' apaga o que foi marcado; o resto fica como o usuario deixou."""
    telas = [_Tela("uw", "ULTRAWIDE", True, True, modo=_Modo(3440, 1440, 160)),
             _Tela("ug", "ULTRAGEAR", True, modo=_Modo(1920, 1080, 180))]
    a, fake = _app(monkeypatch, telas, principal="uw", forcar=False)
    a._enforce_display_defaults()
    assert not [p for p in fake.passos if p[0] == "enabled" and p[2] is False]


def test_sem_arranjo_definido_o_app_nao_opina():
    a = App.__new__(App)
    a.settings = type("S", (), {"display_primary_default": "",
                                "display_off_by_default": []})()
    assert a._tem_arranjo_padrao() is False
    a.settings.display_primary_default = "uw"
    assert a._tem_arranjo_padrao() is True


def test_primaria_e_reconfirmada_depois_de_apagar(monkeypatch):
    """Apagar uma tela faz o Windows reatribuir a primaria por conta propria.

    Medido nesta maquina: pedimos a ULTRAWIDE, a TV foi apagada em seguida, e a
    primaria terminou na ULTRAGEAR — com o log dizendo que a troca dera certo.
    """
    telas = [_Tela("uw", "ULTRAWIDE", True, modo=_Modo(3440, 1440, 160)),
             _Tela("ug", "ULTRAGEAR", True, modo=_Modo(1920, 1080, 180)),
             _Tela("tv", "TV", True, True, modo=_Modo(3840, 2160, 144))]
    a, fake = _app(monkeypatch, telas, principal="uw", apagar=["tv"], forcar=False)

    real = fake.set_enabled

    def apagar_e_bagunçar(device, ligada):
        r = real(device, ligada)
        if not ligada:                      # o Windows escolhe outra primaria
            for t in fake.telas:
                t.primary = t.monitor_id == "ug"
        return r

    fake.set_enabled = apagar_e_bagunçar
    a._enforce_display_defaults()

    assert [t.monitor_id for t in fake.telas if t.primary] == ["uw"]
    assert fake.passos.count(("primary", "dev:uw")) == 2
