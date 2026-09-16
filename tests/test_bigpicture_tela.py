"""Tela onde a grade do Big Picture abre: escolha do usuario, com padrao antigo."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("VANTAGE_NO_FILE_LOG", "1")

import vantage.app as appmod  # noqa: E402
from vantage.app import App  # noqa: E402
from vantage.config import Settings  # noqa: E402


class _Tela:
    def __init__(self, monitor_id, nome, ativa):
        self.monitor_id = monitor_id
        self.name = nome
        self.device = "dev:" + monitor_id
        self.active = ativa


class _Displays:
    def __init__(self, telas):
        self.telas = telas
        self.acesas: list[str] = []

    def list_displays(self, with_modes=False):
        return list(self.telas)

    def set_enabled(self, device, ligada):
        self.acesas.append(device)
        next(t for t in self.telas if t.device == device).active = ligada
        return True, ""


def _app(monkeypatch, telas, alvo="", apagada_por_padrao=""):
    fake = _Displays(telas)
    monkeypatch.setattr(appmod, "dsp", fake)
    # `_tela_qt` pergunta ao Qt por uma tela com aquele nome; aqui so' importa
    # QUAL tela foi escolhida, entao devolvemos o nome.
    monkeypatch.setattr(appmod, "_tela_qt", lambda nome: nome)
    a = App.__new__(App)
    a.settings = Settings()
    a.settings.bigpicture_target = alvo
    a.settings.display_off_by_default = [apagada_por_padrao] if apagada_por_padrao else []
    a._bp_off = ""
    return a, fake


def test_sem_escolha_segue_a_tv_de_jogo(monkeypatch):
    """O padrao antigo continua valendo: a grade acompanha a TV que so' acorda
    para jogar."""
    telas = [_Tela("uw", "ULTRAWIDE", True), _Tela("tv", "Beyond TV", True)]
    a, _ = _app(monkeypatch, telas, alvo="", apagada_por_padrao="tv")

    assert a._acender_tela_de_jogo() == "Beyond TV"


def test_escolha_do_usuario_ganha_da_tv(monkeypatch):
    """O caso que nao existia: querer a grade no monitor de cima."""
    telas = [_Tela("uw", "ULTRAWIDE", True), _Tela("tv", "Beyond TV", True)]
    a, _ = _app(monkeypatch, telas, alvo="screen:uw", apagada_por_padrao="tv")

    assert a._acender_tela_de_jogo() == "ULTRAWIDE"


def test_tela_escolhida_apagada_e_acesa_antes(monkeypatch):
    """De nada adianta mandar a grade para uma tela que esta' fora do desktop."""
    telas = [_Tela("uw", "ULTRAWIDE", True), _Tela("tv", "Beyond TV", False)]
    a, fake = _app(monkeypatch, telas, alvo="screen:tv")

    assert a._acender_tela_de_jogo() == "Beyond TV"
    assert fake.acesas == ["dev:tv"]
    # Guardado para ser apagada de volta quando a grade fechar.
    assert a._bp_off == "tv"


def test_tela_que_nao_existe_mais_nao_quebra(monkeypatch):
    """Monitor desconectado depois de escolhido: cai para a tela primaria."""
    telas = [_Tela("uw", "ULTRAWIDE", True)]
    a, _ = _app(monkeypatch, telas, alvo="screen:sumiu")

    assert a._acender_tela_de_jogo() is None


def test_config_so_aceita_o_formato_de_tela():
    """`primary:` e' vocabulario do atalho de jogo, que troca a principal. A
    grade nao troca; aceitar aqui prometeria o que ela nao faz."""
    for bruto, esperado in (("screen:MON", "screen:MON"), ("primary:MON", ""),
                            ("lixo", ""), (None, ""), (123, "")):
        c = Settings()
        c.bigpicture_target = bruto
        c.sanitize()
        assert c.bigpicture_target == esperado
