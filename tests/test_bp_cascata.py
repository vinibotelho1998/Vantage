"""A cascata de volta do sofa: jogo -> Big Picture -> mesa com a TV apagada.

O degrau que faltava era o ultimo. Quando o jogo devolve para a grade, quem
acendeu a TV foi a sessao, e `_bp_off` chega vazio ao fechamento; a grade
sumia e a TV ficava ligada, mostrando area de trabalho para uma sala vazia.
"""
import vantage.app as appmod
from vantage.app import App

PADRAO = [
    {"monitor_id": "uw", "active": True, "primary": True},
    {"monitor_id": "tv", "active": False, "primary": False},
]


class _Tela:
    def __init__(self, monitor_id, nome, ativa, primaria):
        self.monitor_id = monitor_id
        self.name = nome
        self.device = "dev:" + monitor_id
        self.active = ativa
        self.primary = primaria


class _Displays:
    def __init__(self, telas):
        self.telas = telas
        self.chamadas: list[tuple] = []

    def list_displays(self, with_modes=False):
        return list(self.telas)

    def snapshot(self):
        return [{"monitor_id": t.monitor_id, "active": t.active, "primary": t.primary}
                for t in self.telas]

    def set_enabled(self, device, ligada):
        self.chamadas.append(("enabled", device, ligada))
        next(t for t in self.telas if t.device == device).active = ligada
        return True, ""

    def apply_profile(self, entries, topology=""):
        self.chamadas.append(("profile", topology))
        for e in entries:
            tela = next((t for t in self.telas if t.monitor_id == e["monitor_id"]), None)
            if tela is not None:
                tela.active = e["active"]
                tela.primary = e["primary"]
        return True, ""


def _app(monkeypatch, telas, perfis=None, padrao="PADRAO 2"):
    fake = _Displays(telas)
    monkeypatch.setattr(appmod, "dsp", fake)
    a = App.__new__(App)
    a.settings = type("S", (), {
        "display_profiles": perfis if perfis is not None else
        [{"name": "PADRAO 2", "entries": PADRAO, "topology": "estendido"}],
        "display_default_profile": padrao,
    })()
    return a, fake


def test_tv_acesa_pela_sessao_apaga_ao_fechar_a_grade(monkeypatch):
    """O caso que quebrava: `_bp_off` vazio porque a sessao consumiu ele.

    Sem o perfil padrao entrar aqui, nao havia nada dizendo para apagar a TV.
    """
    telas = [_Tela("uw", "ULTRAWIDE", True, False), _Tela("tv", "Beyond TV", True, True)]
    a, fake = _app(monkeypatch, telas)

    a._voltar_ao_padrao("")

    assert ("profile", "estendido") in fake.chamadas
    assert not next(t for t in telas if t.monitor_id == "tv").active
    assert next(t for t in telas if t.monitor_id == "uw").primary


def test_grade_aberta_da_mesa_nao_mexe_em_nada(monkeypatch):
    """Abrir e fechar a grade sem jogar nao pode fazer as telas piscarem."""
    telas = [_Tela("uw", "ULTRAWIDE", True, True), _Tela("tv", "Beyond TV", False, False)]
    a, fake = _app(monkeypatch, telas)

    a._voltar_ao_padrao("")

    assert fake.chamadas == []


def test_sem_perfil_padrao_apaga_so_o_que_esta_abertura_acendeu(monkeypatch):
    """Comportamento antigo preservado: sem perfil nao ha' estado para voltar."""
    telas = [_Tela("uw", "ULTRAWIDE", True, True), _Tela("tv", "Beyond TV", True, False)]
    a, fake = _app(monkeypatch, telas, perfis=[], padrao="")

    a._voltar_ao_padrao("tv")

    assert fake.chamadas == [("enabled", "dev:tv", False)]


def test_sem_perfil_padrao_nunca_apaga_a_primaria(monkeypatch):
    """Desligar a tela que esta' mandando deixaria a mesa sem imagem nenhuma."""
    telas = [_Tela("tv", "Beyond TV", True, True)]
    a, fake = _app(monkeypatch, telas, perfis=[], padrao="")

    a._voltar_ao_padrao("tv")

    assert fake.chamadas == []


def test_falha_ao_aplicar_o_perfil_nao_derruba_o_fechamento(monkeypatch):
    """A grade tem de fechar mesmo se as telas recusarem; senao o usuario fica
    presos numa tela cheia que nao sai."""
    telas = [_Tela("uw", "ULTRAWIDE", True, False), _Tela("tv", "Beyond TV", True, True)]
    a, fake = _app(monkeypatch, telas)

    def explode(*a, **k):
        raise OSError("driver recusou")

    fake.apply_profile = explode
    a._voltar_ao_padrao("")        # nao pode levantar
